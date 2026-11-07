"""NATS mit einem Nutzer je Dienst (D1.5, nutzer.md Regel 11, ``docker/nats/nats.conf``).

Gegen einen NATS-Server mit genau dieser Konfiguration: ``TEST_NATS_AUTH_URL`` (ohne Zugangsdaten,
etwa ``nats://127.0.0.1:14225``). Die Passwoerter der Nutzer sind dort ``test-<nutzer>``; so
starten ``make test-nats-up`` und die CI den Container. Ohne die Variable uebersprungen.

Geprueft wird, dass ein Dienst fremde Subjects weder senden noch lesen kann: keine fremden Events,
keine fremden Consumer, keine Nachrichten aus dem Stream, keine fremden RPC und keine fremde Inbox.
Dass jeder Dienst mit seinen Rechten auskommt, zeigt der E2E-Stack mit derselben Datei.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import pytest

BASE = os.environ.get("TEST_NATS_AUTH_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not BASE, reason="TEST_NATS_AUTH_URL nicht gesetzt (make test-nats-up)"
)

SERVICES = ("market-data", "scoring", "notification", "web-api")
TIMEOUT = 1.0


def url(user: str) -> str:
    parts = urlsplit(BASE)
    return f"{parts.scheme}://{user}:test-{user}@{parts.netloc}"


class Connection:
    """Eine Verbindung als ``user``; Rechteverstoesse meldet NATS nur ueber ``error_cb``."""

    def __init__(self, user: str) -> None:
        self.user = user
        self.errors: list[str] = []
        self.nc: Any = None

    async def __aenter__(self) -> Connection:
        import nats

        from va_platform.nats import inbox_prefix

        async def on_error(error: Exception) -> None:
            self.errors.append(str(error))

        self.nc = await nats.connect(
            url(self.user),
            error_cb=on_error,
            inbox_prefix=inbox_prefix(url(self.user)),
            allow_reconnect=False,
            connect_timeout=5,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        with contextlib.suppress(Exception):
            await self.nc.close()

    async def violations(self) -> list[str]:
        """Die Verstoesse bis jetzt; flush holt die Antwort des Servers ab."""
        with contextlib.suppress(Exception):
            await self.nc.flush(timeout=2)
        await asyncio.sleep(0.2)
        return [e for e in self.errors if "permissions violation" in e.lower()]


def _run(scenario: Callable[[], Awaitable[None]]) -> None:
    async def main() -> None:
        from nats.js.errors import NotFoundError

        from va_platform.nats import provision

        # Frischer Stream mit allen Consumern, angelegt vom Nutzer mit allen Rechten
        async with Connection("batch") as admin:
            jsm = admin.nc.jsm()
            for stream in ("VA_EVENTS", "VA_PRIVATE"):
                with contextlib.suppress(NotFoundError):
                    await jsm.delete_stream(stream)
            await provision(jsm)
        await scenario()

    asyncio.run(main())


async def _connect_and_close(target: str) -> None:
    import nats

    nc = await nats.connect(target, allow_reconnect=False, connect_timeout=2)
    await nc.close()


async def _fetch_from(js: Any, consumer: str) -> None:
    sub = await js.pull_subscribe_bind(durable=consumer, stream="VA_EVENTS")
    await sub.fetch(1, timeout=TIMEOUT)


def test_without_user_no_connection():
    async def scenario() -> None:
        with pytest.raises(Exception):  # noqa: B017, PT011 - nats-py meldet verschieden
            await _connect_and_close(BASE)

    _run(scenario)


def test_wrong_password_no_connection():
    async def scenario() -> None:
        parts = urlsplit(BASE)
        with pytest.raises(Exception):  # noqa: B017, PT011
            await _connect_and_close(f"{parts.scheme}://scoring:falsch@{parts.netloc}")

    _run(scenario)


# Was jeder Dienst beim Start anlegt (D1.6: notification auch den privaten Consumer, das web-api
# den privaten Stream, in den es sendet)
OWN = {
    "market-data": {"consumers": ("market-data",)},
    "scoring": {"consumers": ("scoring",)},
    "notification": {"consumers": ("notification", "notification-private")},
    "web-api": {"consumers": ("web-api",), "streams": ("VA_EVENTS", "VA_PRIVATE")},
}


@pytest.mark.parametrize("service", SERVICES)
def test_each_service_starts_its_bus_with_its_own_consumer(service):
    from va_platform.nats.bus import NatsBus

    def scenario_sync() -> None:
        bus = NatsBus(url(service), **OWN[service])  # type: ignore[arg-type]
        bus.start()
        bus.close()

    async def scenario() -> None:
        await asyncio.to_thread(scenario_sync)

    _run(scenario)


@pytest.mark.parametrize(
    ("service", "subject"),
    [
        ("market-data", "va.marketdata.snapshot.completed"),
        ("scoring", "va.scoring.run.completed"),
        ("notification", "va.notification.report.sent"),
        ("web-api", "va.screening.run.requested"),
        ("market-data", "va.screening.run.failed"),
    ],
)
def test_a_service_publishes_its_own_events(service, subject):
    async def scenario() -> None:
        async with Connection(service) as c:
            ack = await c.nc.jetstream().publish(subject, b"{}", timeout=TIMEOUT * 3)
            assert ack.stream == "VA_EVENTS"

    _run(scenario)


@pytest.mark.parametrize(
    ("service", "subject"),
    [
        ("market-data", "va.scoring.run.completed"),
        ("scoring", "va.screening.run.requested"),
        ("notification", "va.marketdata.snapshot.completed"),
        ("web-api", "va.notification.report.sent"),
    ],
)
def test_no_service_publishes_foreign_events(service, subject):
    async def scenario() -> None:
        async with Connection(service) as c:
            with pytest.raises(Exception):  # noqa: B017, PT011 - kein PubAck
                await c.nc.jetstream().publish(subject, b"{}", timeout=TIMEOUT)
            assert await c.violations()
        async with Connection("batch") as admin:
            assert (await admin.nc.jsm().stream_info("VA_EVENTS")).state.messages == 0

    _run(scenario)


@pytest.mark.parametrize("service", ["market-data", "scoring", "notification"])
def test_no_service_listens_to_the_events_directly(service):
    async def scenario() -> None:
        async with Connection(service) as c:
            await c.nc.subscribe("va.>")
            assert await c.violations()

    _run(scenario)


@pytest.mark.parametrize(
    ("service", "consumer"),
    [("market-data", "scoring"), ("scoring", "notification"), ("notification", "web-api")],
)
def test_no_service_reads_a_foreign_consumer(service, consumer):
    async def scenario() -> None:
        async with Connection(service) as c:
            with pytest.raises(Exception):  # noqa: B017, PT011 - keine Antwort der API
                await _fetch_from(c.nc.jetstream(), consumer)
            assert await c.violations()

    _run(scenario)


@pytest.mark.parametrize("service", ["market-data", "scoring", "notification"])
def test_only_the_web_api_reads_messages_from_the_stream(service):
    """Der Replayer des web-api liest einzelne Nachrichten; die Dienste nicht."""

    async def scenario() -> None:
        async with Connection("market-data") as producer:
            await producer.nc.jetstream().publish("va.screening.run.failed", b"{}")
        async with Connection("web-api") as web:
            message = await web.nc.jsm().get_msg("VA_EVENTS", 1)
            assert message.subject == "va.screening.run.failed"
        async with Connection(service) as c:
            with pytest.raises(Exception):  # noqa: B017, PT011
                await asyncio.wait_for(c.nc.jsm().get_msg("VA_EVENTS", 1), TIMEOUT)

    _run(scenario)


@pytest.mark.parametrize(
    ("service", "inbox"),
    [("market-data", "_INBOX.web-api.>"), ("scoring", "_INBOX.>"), ("web-api", "_INBOX.scoring.>")],
)
def test_no_service_reads_a_foreign_inbox(service, inbox):
    async def scenario() -> None:
        async with Connection(service) as c:
            await c.nc.subscribe(inbox)
            assert await c.violations()

    _run(scenario)


@pytest.mark.parametrize("service", SERVICES)
def test_no_service_reconfigures_the_stream(service):
    """Nur batch stellt den Stream um; ein Dienst koennte sonst die Events aller verwerfen."""

    async def scenario() -> None:
        async with Connection(service) as c:
            jsm = c.nc.jsm()
            config = (await jsm.stream_info("VA_EVENTS")).config
            config.max_age = 1.0
            with pytest.raises(Exception):  # noqa: B017, PT011 - keine Antwort der API
                await asyncio.wait_for(jsm.update_stream(config), TIMEOUT * 3)
            assert await c.violations()
        async with Connection("batch") as admin:
            assert (await admin.nc.jsm().stream_info("VA_EVENTS")).config.max_age > 1.0

    _run(scenario)


@pytest.mark.parametrize("service", SERVICES)
def test_a_service_starts_even_if_the_stream_drifted(service):
    """Weicht der Stream ab, laeuft der Dienst weiter und meldet es (make nats-provision)."""
    from va_platform.nats.bus import NatsBus

    async def scenario() -> None:
        async with Connection("batch") as admin:
            jsm = admin.nc.jsm()
            config = (await jsm.stream_info("VA_EVENTS")).config
            config.duplicate_window = 60.0
            await jsm.update_stream(config)

        def start_and_stop() -> None:
            bus = NatsBus(url(service), consumers=(service,))
            bus.start()
            bus.close()

        await asyncio.to_thread(start_and_stop)

    _run(scenario)


class TestPrivateStream:
    """D1.6: VA_PRIVATE (priv.va.>) nur fuer die, die ihn brauchen: Das web-api sendet die
    Bestaetigung, notification liest sie ueber notification-private. Sonst niemand."""

    SUBJECT = "priv.va.identity.email_confirmation.requested"

    def test_the_web_api_sends_and_notification_reads(self):
        async def scenario() -> None:
            async with Connection("web-api") as web:
                ack = await web.nc.jetstream().publish(self.SUBJECT, b"{}", timeout=TIMEOUT * 3)
                assert ack.stream == "VA_PRIVATE"
            async with Connection("notification") as notify:
                sub = await notify.nc.jetstream().pull_subscribe_bind(
                    durable="notification-private", stream="VA_PRIVATE"
                )
                [message] = await sub.fetch(1, timeout=TIMEOUT * 3)
                await message.ack()
                assert not await notify.violations()

        _run(scenario)

    @pytest.mark.parametrize("service", ["market-data", "scoring", "notification"])
    def test_nobody_else_sends_private_events(self, service):
        async def scenario() -> None:
            async with Connection(service) as c:
                with pytest.raises(Exception):  # noqa: B017, PT011 - kein PubAck
                    await c.nc.jetstream().publish(self.SUBJECT, b"{}", timeout=TIMEOUT)
                assert await c.violations()

        _run(scenario)

    @pytest.mark.parametrize("service", ["market-data", "scoring", "web-api"])
    def test_nobody_else_reads_the_private_stream(self, service):
        async def scenario() -> None:
            async with Connection("web-api") as web:
                await web.nc.jetstream().publish(self.SUBJECT, b"{}", timeout=TIMEOUT * 3)
            async with Connection(service) as c:
                with pytest.raises(Exception):  # noqa: B017, PT011
                    await asyncio.wait_for(c.nc.jsm().get_msg("VA_PRIVATE", 1), TIMEOUT)
                with pytest.raises(Exception):  # noqa: B017, PT011
                    await _fetch_private(c.nc.jetstream())
                assert await c.violations()

        _run(scenario)


async def _fetch_private(js: Any) -> None:
    sub = await js.pull_subscribe_bind(durable="notification-private", stream="VA_PRIVATE")
    await sub.fetch(1, timeout=TIMEOUT)


class TestRpc:
    @staticmethod
    async def _serve(c: Connection, subject: str) -> None:
        async def reply(message: Any) -> None:
            await message.respond(b"pong")

        await c.nc.subscribe(subject, queue="q", cb=reply)
        await c.nc.flush()

    def test_the_web_api_asks_and_the_owner_answers(self):
        async def scenario() -> None:
            async with Connection("scoring") as scoring, Connection("notification") as notify:
                await self._serve(scoring, "rpc.va.scoring.preview")
                await self._serve(notify, "rpc.va.notification.report")
                async with Connection("web-api") as web:
                    for subject in ("rpc.va.scoring.preview", "rpc.va.notification.report"):
                        answer = await web.nc.request(subject, b"ping", timeout=TIMEOUT * 3)
                        assert answer.data == b"pong"
                assert not await scoring.violations()
                assert not await notify.violations()

        _run(scenario)

    def test_market_data_answers_the_securities_search(self):
        """D2.1: Suche und Aufloesung von Wertpapieren beantwortet market-data."""

        async def scenario() -> None:
            async with Connection("market-data") as market:
                await self._serve(market, "rpc.va.marketdata.securities.search")
                async with Connection("web-api") as web:
                    answer = await web.nc.request(
                        "rpc.va.marketdata.securities.search", b"ping", timeout=TIMEOUT * 3
                    )
                    assert answer.data == b"pong"
                assert not await market.violations()

        _run(scenario)

    @pytest.mark.parametrize(
        ("service", "subject"),
        [
            ("notification", "rpc.va.scoring.>"),
            ("scoring", "rpc.va.notification.>"),
            ("scoring", "rpc.va.marketdata.>"),
            ("market-data", "rpc.va.>"),
            ("market-data", "rpc.va.scoring.>"),
            ("web-api", "rpc.va.scoring.>"),
        ],
    )
    def test_nobody_answers_for_someone_else(self, service, subject):
        async def scenario() -> None:
            async with Connection(service) as c:
                await c.nc.subscribe(subject)
                assert await c.violations()

        _run(scenario)

    @pytest.mark.parametrize("service", ["market-data", "scoring", "notification"])
    def test_only_the_web_api_asks(self, service):
        async def scenario() -> None:
            async with Connection(service) as c:
                with pytest.raises(Exception):  # noqa: B017, PT011
                    await c.nc.request("rpc.va.notification.report", b"ping", timeout=TIMEOUT)
                assert await c.violations()

        _run(scenario)
