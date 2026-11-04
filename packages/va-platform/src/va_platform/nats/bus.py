"""``EventBus`` ueber NATS JetStream (P4.3, docs/architecture/events.md, ADR-0002 mit Nachtrag).

Nach aussen synchron wie ``InProcessBus``, damit Handler und Batch gleich bleiben. Innen laeuft
eine Event-Loop in einem eigenen Thread, die Handler laufen in einem Thread-Pool und duerfen
selbst ``publish`` aufrufen.

- **Stream:** ``start`` ruft ``provision`` aus P4.1. Der Stream entsteht nur so, wie er dort
  vorgegeben ist.
- **Consumer:** Einen provisionierten Consumer nutzt der Bus, wie er ist. Sein Filter muss das
  abonnierte Subject abdecken. Einen unbekannten Namen (Tests) legt der Bus mit genau den
  abonnierten Subjects an, nur fuer neue Nachrichten. Je Consumer holt eine Schleife die
  Nachrichten einzeln ab und verteilt sie nach Event-Typ, einen Typ ohne Handler bestaetigt
  sie ungelesen.
- **Senden:** ueber den ``JetStreamPublisher`` aus P4.2 (``Nats-Msg-Id`` = Event-ID). Folge-
  Events liegen im Stream, bevor das ausloesende Event bestaetigt wird. Fluechtige Events gehen
  ueber Core-NATS am Stream vorbei.
- **Wiederholung:** Es gilt die Grenze des Busses (``max_deliver``), wie im Prozess. Danach
  Dead-Letter-Callback und ``term()``, vorher ``nak()``. Solange ein Handler laeuft, sendet der
  Bus In-Progress-Acks, sonst stellte JetStream nach ``ack_wait`` erneut zu.
- **Request/Reply (P4.8):** ``call`` und ``serve`` auf ``rpc.va.…`` ueber Core-NATS. Ein Server
  antwortet je Queue-Gruppe; Fehler kommen als ``error`` in der Antwort zurueck. Antwortet
  niemand, wirft ``call`` ``RpcUnavailable``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import nats
import nats.errors
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.errors import NotFoundError
from pydantic import ValidationError

from va_contracts import Envelope, parse_envelope
from va_contracts.events.v1 import BY_DATASCHEMA
from va_contracts.rpc.v1 import RpcErrorV1

from ..bus import DeadLetter, _readable
from ..messaging import OutboxMessage
from . import ACK_WAIT, MAX_DELIVER, STREAM_NAME, JetStreamPublisher, provision

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

    from nats.aio.client import Client
    from nats.aio.msg import Msg
    from nats.js.client import JetStreamContext

    from va_contracts import Contract
    from va_contracts.events.v1 import EventSpec
    from va_contracts.rpc.v1 import RpcReplyV1, RpcSpec

    from ..bus import Handler

log = logging.getLogger(__name__)

FETCH_TIMEOUT = 1.0  # so lange wartet eine Abholung; danach prueft die Schleife ``close``
# Beim Start schnell aufgeben (der Aufrufer meldet oder versucht es spaeter), im Lauf dagegen
# lange neu verbinden, etwa wenn NATS neu startet. nats-py wartet 2 s zwischen den Versuchen.
CONNECT_ATTEMPTS = 3
RECONNECT_ATTEMPTS = 60

RPC_TIMEOUT = 30.0  # P4.8: so lange wartet ``call``; die Vorschau rechnet auf dem J4125 Sekunden


class RpcUnavailable(Exception):
    """Request/Reply ohne Antwort: niemand abonniert (NATS meldet das sofort) oder Zeit abgelaufen."""


# Stream-Sequenz der Nachricht, die der Handler gerade verarbeitet (P4.4); je Handler-Thread
_SEQUENCE: ContextVar[int | None] = ContextVar("va-nats-sequence", default=None)


def current_sequence() -> int | None:
    """Stream-Sequenz des Events, das der aufrufende Handler gerade verarbeitet.

    ``None`` ausserhalb einer Zustellung ueber NATS. Das web-api reicht sie an den WebSocket
    weiter, damit ein Client nach einem Abbruch mit ``resumeFrom`` aufholen kann (P4.5).
    """
    return _SEQUENCE.get()


def covers(pattern: str, subject: str) -> bool:
    """Deckt der NATS-Filter ``pattern`` (mit ``*`` und ``>``) das ``subject`` ab?"""
    tokens, parts = pattern.split("."), subject.split(".")
    for i, token in enumerate(tokens):
        if token == ">":
            return len(parts) > i
        if i >= len(parts) or token not in ("*", parts[i]):
            return False
    return len(tokens) == len(parts)


class NatsBus:
    """``EventBus`` ueber JetStream: ``start``, dann ``subscribe``/``publish``, am Ende ``close``."""

    def __init__(
        self,
        url: str,
        *,
        max_deliver: int = 1,
        on_dead_letter: Callable[[DeadLetter], None] | None = None,
        retry_delay: float = 1.0,
        ack_wait: float = ACK_WAIT,
        timeout: float = 10.0,
    ) -> None:
        if not 1 <= max_deliver <= MAX_DELIVER:
            # Darueber verwuerfe NATS das Event still, ohne Dead Letter
            msg = f"max_deliver muss zwischen 1 und {MAX_DELIVER} liegen, nicht {max_deliver}"
            raise ValueError(msg)
        self._url = url
        self._max_deliver = max_deliver
        self._on_dead_letter = on_dead_letter
        self._retry_delay = retry_delay
        self._ack_wait = ack_wait  # nur fuer Consumer, die der Bus selbst anlegt
        self._timeout = timeout
        self._handlers: dict[str, dict[str, Handler[Any]]] = {}
        self._volatile: dict[str, dict[str, Handler[Any]]] = {}  # Core-NATS, P4.5
        self._created: set[str] = set()  # Consumer, die der Bus selbst angelegt hat
        self._pullers: dict[str, asyncio.Task[None]] = {}
        self._inflight = 0  # nur in der Event-Loop veraendert
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="nats-handler")
        self._nc: Client | None = None
        self._js: JetStreamContext | None = None
        self._publisher: JetStreamPublisher | None = None

    # -- Lebenszyklus ----------------------------------------------------------------------

    def start(self) -> None:
        if self._loop is not None:
            msg = "NatsBus laeuft bereits"
            raise RuntimeError(msg)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="nats-bus", daemon=True)
        thread.start()
        self._loop, self._thread = loop, thread
        try:
            self._call(self._connect())
        except BaseException:
            self._stop_loop()
            raise

    def close(self, timeout: float = 30.0) -> None:
        """Holt nichts Neues mehr ab, laesst laufende Handler zu Ende laufen, trennt dann."""
        if self._loop is None or self._closing:
            return
        self._closing = True
        try:
            self._call(self._shutdown(timeout), timeout=timeout + self._timeout)
        except Exception:
            log.warning("NatsBus: Schliessen nicht sauber", exc_info=True)
        finally:
            self._stop_loop()

    def __enter__(self) -> NatsBus:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- EventBus --------------------------------------------------------------------------

    def subscribe[T: Contract](
        self, spec: EventSpec[T], consumer: str, handler: Handler[T]
    ) -> None:
        if spec.volatile:
            self._subscribe_volatile(spec, consumer, handler)
            return
        handlers = self._handlers.setdefault(consumer, {})
        if spec.type in handlers:
            msg = f"{consumer} hat {spec.type} bereits abonniert"
            raise ValueError(msg)
        # Erst eintragen, dann binden: Sonst bestaetigte die Schleife ein frueh eintreffendes
        # Event ungelesen, weil es noch keinen Handler gibt.
        handlers[spec.type] = handler
        try:
            self._call(self._bind(consumer))
        except BaseException:
            del handlers[spec.type]
            raise

    def _subscribe_volatile(
        self, spec: EventSpec[Any], consumer: str, handler: Handler[Any]
    ) -> None:
        """Fluechtige Events (``live.va.…``, P4.5): Core-NATS, ohne Stream und Wiederholung."""
        handlers = self._volatile.setdefault(consumer, {})
        if spec.type in handlers:
            msg = f"{consumer} hat {spec.type} bereits abonniert"
            raise ValueError(msg)
        handlers[spec.type] = handler
        try:
            self._call(self._listen(spec.subject, handler))
        except BaseException:
            del handlers[spec.type]
            raise

    async def _listen(self, subject: str, handler: Handler[Any]) -> None:
        loop = asyncio.get_running_loop()

        async def on_message(message: Msg) -> None:
            # nats-py ruft das je Abo nacheinander auf: Die Reihenfolge bleibt erhalten
            try:
                await loop.run_in_executor(self._pool, _deliver_volatile, handler, message.data)
            except Exception:
                log.warning("Fluechtiges Event auf %s nicht verarbeitet", subject, exc_info=True)

        await self._client().subscribe(subject, cb=on_message)

    def publish(self, envelope: Envelope[Any]) -> None:
        spec = BY_DATASCHEMA[envelope.dataschema]
        payload = envelope.model_dump_json().encode()
        if spec.volatile:
            self._call(self._client().publish(spec.subject, payload))
            return
        assert self._publisher is not None, "start() fehlt"
        message = OutboxMessage(envelope.id, spec.subject, payload)
        self._call(self._publisher.publish(message))

    # -- Request/Reply (P4.8) --------------------------------------------------------------

    def call[Q: Contract, R: RpcReplyV1](
        self, spec: RpcSpec[Q, R], request: Q, *, timeout: float = RPC_TIMEOUT
    ) -> R:
        """Schickt die Anfrage und wartet auf die Antwort; ``RpcUnavailable`` ohne Antwort."""
        payload = request.model_dump_json().encode()
        try:
            message = self._call(
                self._client().request(spec.subject, payload, timeout=timeout),
                timeout=timeout + self._timeout,
            )
        except (nats.errors.NoRespondersError, nats.errors.TimeoutError, TimeoutError) as e:
            raise RpcUnavailable(spec.name) from e
        return spec.reply.model_validate_json(message.data)

    def serve[Q: Contract, R: RpcReplyV1](
        self, spec: RpcSpec[Q, R], handler: Callable[[Q], R], *, queue: str
    ) -> None:
        """Beantwortet Anfragen auf ``spec.subject`` im Thread-Pool, nacheinander.

        Mehrere Server derselben ``queue`` teilen sich die Anfragen. Passt eine Anfrage nicht zum
        Modell, antwortet der Bus mit ``invalid``, wirft der Handler, mit ``internal``.
        """
        self._call(self._serve(spec, handler, queue))

    async def _serve(
        self, spec: RpcSpec[Any, Any], handler: Callable[[Any], Any], queue: str
    ) -> None:
        loop = asyncio.get_running_loop()

        async def on_message(message: Msg) -> None:
            reply = await loop.run_in_executor(self._pool, _answer, spec, handler, message.data)
            try:
                await message.respond(reply)
            except Exception:
                log.warning("Antwort auf %s nicht gesendet", spec.subject, exc_info=True)

        await self._client().subscribe(spec.subject, queue=queue, cb=on_message)

    def settle(self, timeout: float = 30.0) -> None:
        """Wartet, bis die eigenen Consumer nichts mehr offen haben und kein Handler laeuft.

        Zweimal hintereinander geprueft: Ein Handler veroeffentlicht seine Folge-Events vor
        dem Ack, beim zweiten Blick stehen sie also bei ihren Consumern.
        """
        deadline = time.monotonic() + timeout
        quiet = 0
        while quiet < 2:
            quiet = 0 if self._call(self._busy()) else quiet + 1
            if time.monotonic() > deadline:
                msg = f"NatsBus: nach {timeout:.0f} s noch Events offen"
                raise TimeoutError(msg)
            time.sleep(0.05)

    # -- intern: Thread und Loop -----------------------------------------------------------

    def _call[R](self, coro: Coroutine[Any, Any, R], timeout: float | None = None) -> R:
        if self._loop is None:
            coro.close()
            msg = "NatsBus ist nicht gestartet"
            raise RuntimeError(msg)
        if threading.current_thread() is self._thread:
            coro.close()
            msg = "NatsBus: synchrone Aufrufe nicht aus der eigenen Event-Loop"
            raise RuntimeError(msg)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout if timeout is not None else self._timeout * 3)
        except TimeoutError:
            future.cancel()  # sonst liefe die Koroutine in der Loop weiter
            raise

    def _stop_loop(self) -> None:
        loop, thread = self._loop, self._thread
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=10)
        if loop is not None and not loop.is_running():
            loop.close()
        self._pool.shutdown(wait=False)

    def _client(self) -> Client:
        assert self._nc is not None, "start() fehlt"
        return self._nc

    async def _connect(self) -> None:
        self._nc = await nats.connect(
            self._url,
            connect_timeout=self._timeout,
            name="va-bus",
            max_reconnect_attempts=CONNECT_ATTEMPTS,
        )
        # Dieselbe Grenze gilt bei nats-py fuer den Start und spaetere Abbrueche; erst nach dem
        # Start auf die lange Grenze stellen
        self._nc.options["max_reconnect_attempts"] = RECONNECT_ATTEMPTS
        self._js = self._nc.jetstream()
        self._publisher = JetStreamPublisher(self._js, timeout=self._timeout)
        await provision(self._nc.jsm())

    async def _shutdown(self, timeout: float) -> None:
        pullers = list(self._pullers.values())
        if pullers:
            _done, pending = await asyncio.wait(pullers, timeout=timeout)
            for task in pending:
                task.cancel()
        if self._nc is not None and not self._nc.is_closed:
            # Kein drain(): Die Abholschleifen sind beendet, es haengt nichts mehr an den
            # Abos. flush() bringt die letzten Acks zum Server.
            try:
                await self._nc.flush(timeout=int(self._timeout))
            except Exception:
                log.warning("NatsBus: letzte Acks nicht bestaetigt", exc_info=True)
            await self._nc.close()

    # -- intern: Consumer ------------------------------------------------------------------

    async def _bind(self, consumer: str) -> None:
        jsm = self._client().jsm()
        subjects = sorted(BY_TYPE_SUBJECT[t] for t in self._handlers[consumer])
        try:
            info = await jsm.consumer_info(STREAM_NAME, consumer)
        except NotFoundError:
            info = None
        if info is None or consumer in self._created:
            # Unbekannt (Tests): Der Bus legt ihn mit genau seinen Subjects an, ohne Altlasten
            config = ConsumerConfig(
                durable_name=consumer,
                ack_policy=AckPolicy.EXPLICIT,
                max_deliver=MAX_DELIVER,
                ack_wait=self._ack_wait,
                deliver_policy=DeliverPolicy.NEW,
            )
            if len(subjects) == 1:
                config.filter_subject = subjects[0]
            else:
                config.filter_subjects = subjects
            await jsm.add_consumer(STREAM_NAME, config)
            self._created.add(consumer)
            ack_wait = self._ack_wait
        else:
            filters = info.config.filter_subjects or [info.config.filter_subject or ""]
            missing = [s for s in subjects if not any(covers(f, s) for f in filters)]
            if missing:
                msg = (
                    f"Consumer {consumer} deckt {', '.join(missing)} nicht ab "
                    f"(Filter: {', '.join(filters)}); die Provisionierung anpassen"
                )
                raise ValueError(msg)
            ack_wait = info.config.ack_wait or ACK_WAIT
        if consumer not in self._pullers:
            assert self._js is not None
            sub = await self._js.pull_subscribe_bind(durable=consumer, stream=STREAM_NAME)
            loop = asyncio.get_running_loop()
            self._pullers[consumer] = loop.create_task(self._pull(consumer, sub, ack_wait))

    async def _pull(self, consumer: str, sub: Any, ack_wait: float) -> None:
        while not self._closing:
            try:
                messages = await sub.fetch(batch=1, timeout=FETCH_TIMEOUT)
            except nats.errors.TimeoutError:
                continue
            except Exception:
                if self._closing:
                    break
                log.warning("%s: Abholen gescheitert, neuer Versuch", consumer, exc_info=True)
                await asyncio.sleep(1.0)
                continue
            for message in messages:  # auch beim Schliessen: abgeholt ist abgeholt
                await self._handle(consumer, message, ack_wait)

    async def _busy(self) -> bool:
        if self._inflight:
            return True
        jsm = self._client().jsm()
        for consumer in self._pullers:
            info = await jsm.consumer_info(STREAM_NAME, consumer)
            if info.num_pending or info.num_ack_pending:
                return True
        return False

    # -- intern: Zustellung ----------------------------------------------------------------

    async def _handle(self, consumer: str, message: Msg, ack_wait: float) -> None:
        """Eine Nachricht verarbeiten. Wirft nie, sonst stuende die Schleife des Consumers."""
        self._inflight += 1
        try:
            await self._dispatch(consumer, message, ack_wait)
        except Exception:
            log.exception("%s: Nachricht auf %s nicht verarbeitet", consumer, message.subject)
        finally:
            self._inflight -= 1

    async def _dispatch(self, consumer: str, message: Msg, ack_wait: float) -> None:
        raw = message.data
        try:
            head = Envelope[dict[str, Any]].model_validate_json(raw)
        except Exception:
            log.error("%s: unlesbare Nachricht auf %s verworfen", consumer, message.subject)
            await message.term()
            return
        handler = self._handlers.get(consumer, {}).get(head.type)
        if handler is None:
            await message.ack()  # nicht fuer diesen Consumer bestimmt
            return
        attempt = message.metadata.num_delivered
        loop = asyncio.get_running_loop()
        try:
            async with _keep_alive(message, ack_wait):
                await loop.run_in_executor(
                    self._pool, _deliver, handler, raw, message.metadata.sequence.stream
                )
        except Exception as error:
            log.warning(
                "%s: %s (%s) fehlgeschlagen, Versuch %d/%d",
                consumer,
                head.type,
                head.id,
                attempt,
                self._max_deliver,
                exc_info=True,
            )
            if attempt < self._max_deliver:
                await message.nak(delay=self._retry_delay)
                return
            dead = DeadLetter(consumer, _readable(raw.decode(), head), attempt, error)
            await loop.run_in_executor(self._pool, self._dead_letter, dead)
            await message.term()
            return
        await message.ack()

    def _dead_letter(self, dead: DeadLetter) -> None:
        log.error(
            "%s: %s (%s) nach %d Versuchen aufgegeben",
            dead.consumer,
            dead.envelope.type,
            dead.envelope.id,
            dead.attempts,
        )
        if self._on_dead_letter is not None:
            try:
                self._on_dead_letter(dead)
            except Exception:
                log.exception("%s: Dead-Letter-Callback gescheitert", dead.consumer)


BY_TYPE_SUBJECT = {spec.type: spec.subject for spec in BY_DATASCHEMA.values()}


def _answer(spec: RpcSpec[Any, Any], handler: Callable[[Any], Any], raw: bytes) -> bytes:
    """Eine Anfrage von NATS beantworten; eine ungueltige wird zur Antwort mit ``invalid``."""
    try:
        request = spec.request.model_validate_json(raw)
    except ValidationError as e:
        reply = spec.reply(error=RpcErrorV1(code="invalid", message=str(e)))
    else:
        reply = answer_request(spec, handler, request)
    return reply.model_dump_json().encode()


def answer_request[R: RpcReplyV1](
    spec: RpcSpec[Any, R], handler: Callable[[Any], R], request: Any
) -> R:
    """Den Handler aufrufen; eine Exception wird zur Antwort mit ``internal`` (auch im Prozess)."""
    try:
        return handler(request)
    except Exception as e:
        log.exception("%s: Anfrage nicht beantwortet", spec.name)
        return spec.reply(error=RpcErrorV1(code="internal", message=f"{type(e).__name__}: {e}"))


def _deliver_volatile(handler: Handler[Any], raw: bytes) -> None:
    handler(parse_envelope(raw))  # ohne Stream-Sequenz: current_sequence() bleibt None


def _deliver(handler: Handler[Any], raw: bytes, sequence: int) -> None:
    # Im Versuch geparst: Eine unbekannte Payload zaehlt wie ein gescheiterter Handler
    token = _SEQUENCE.set(sequence)
    try:
        handler(parse_envelope(raw))
    finally:
        _SEQUENCE.reset(token)


@contextlib.asynccontextmanager
async def _keep_alive(message: Msg, ack_wait: float) -> AsyncIterator[None]:
    """In-Progress-Acks alle ``ack_wait / 3`` Sekunden, solange der Block laeuft."""

    async def beat() -> None:
        while True:
            await asyncio.sleep(ack_wait / 3)
            try:
                await message.in_progress()
            except Exception:
                log.debug("In-Progress-Ack gescheitert", exc_info=True)

    task = asyncio.get_running_loop().create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
