"""Request/Reply ueber den ``NatsBus`` (P4.8): ``call`` und ``serve`` auf Core-NATS.

Die Anfrage geht an ``rpc.va.<name>``, ein Server in der Queue-Gruppe antwortet. Fehler kommen als
``error`` in der Antwort zurueck, nicht als Exception: Eine ungueltige Anfrage ergibt ``invalid``,
eine Exception im Handler ``internal``. Antwortet niemand, wirft ``call`` ``RpcUnavailable``.
Ohne ``TEST_NATS_URL`` uebersprungen.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import pytest

from va_contracts.profile import ProfileParamsV1
from va_contracts.rpc.v1 import (
    PROFILE_ACTIVATE,
    PROFILE_SAVE,
    ActivateReplyV1,
    ActivateRequestV1,
    RpcErrorV1,
    SaveVersionReplyV1,
    SaveVersionRequestV1,
)
from va_platform.nats import NatsBus, RpcUnavailable


@pytest.fixture
def server(nats_url: str) -> Iterator[NatsBus]:
    bus = NatsBus(nats_url)
    bus.start()
    yield bus
    bus.close()


@pytest.fixture
def client(nats_url: str) -> Iterator[NatsBus]:
    bus = NatsBus(nats_url, timeout=2.0)
    bus.start()
    yield bus
    bus.close()


def _save(based_on: int = 2) -> SaveVersionRequestV1:
    return SaveVersionRequestV1(
        profile_id=1, params=ProfileParamsV1(), based_on=based_on, comment="Test"
    )


def test_a_request_gets_its_reply(server, client):
    calls: list[SaveVersionRequestV1] = []

    def save(request: SaveVersionRequestV1) -> SaveVersionReplyV1:
        calls.append(request)
        return SaveVersionReplyV1(version=request.based_on + 1)

    server.serve(PROFILE_SAVE, save, queue="scoring")
    reply = client.call(PROFILE_SAVE, _save())

    assert reply == SaveVersionReplyV1(version=3)
    assert calls == [_save()]


def test_a_typed_error_comes_back(server, client):
    def save(request: SaveVersionRequestV1) -> SaveVersionReplyV1:
        error = RpcErrorV1(code="conflict", message="nicht die neueste", newest=5)
        return SaveVersionReplyV1(error=error)

    server.serve(PROFILE_SAVE, save, queue="scoring")
    reply = client.call(PROFILE_SAVE, _save())
    assert reply.error is not None
    assert (reply.error.code, reply.error.newest) == ("conflict", 5)


def test_an_exception_in_the_handler_is_internal(server, client):
    def activate(request: ActivateRequestV1) -> ActivateReplyV1:
        msg = "Datenbank weg"
        raise RuntimeError(msg)

    server.serve(PROFILE_ACTIVATE, activate, queue="scoring")
    reply = client.call(PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2))
    assert reply.error is not None
    assert reply.error.code == "internal"
    assert "Datenbank weg" in reply.error.message


def test_an_invalid_request_is_rejected(server, nats_url):
    server.serve(PROFILE_ACTIVATE, lambda request: ActivateReplyV1(), queue="scoring")

    async def raw() -> bytes:
        import nats

        nc = await nats.connect(nats_url)
        try:
            message = await nc.request(PROFILE_ACTIVATE.subject, b'{"version": 0}', timeout=5)
            return message.data
        finally:
            await nc.close()

    reply = ActivateReplyV1.model_validate_json(asyncio.run(raw()))
    assert reply.error is not None
    assert reply.error.code == "invalid"


def test_without_a_server_the_call_fails_fast(client):
    started = time.monotonic()
    with pytest.raises(RpcUnavailable):
        client.call(PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2))
    assert time.monotonic() - started < 2.0  # NATS meldet "no responders" sofort


def test_a_slow_server_times_out(server, client):
    release = threading.Event()

    def activate(request: ActivateRequestV1) -> ActivateReplyV1:
        release.wait(5)
        return ActivateReplyV1()

    server.serve(PROFILE_ACTIVATE, activate, queue="scoring")
    try:
        with pytest.raises(RpcUnavailable):
            client.call(PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2), timeout=0.5)
    finally:
        release.set()


def test_one_server_of_the_queue_group_answers(server, nats_url, client):
    second = NatsBus(nats_url)
    second.start()
    answered: list[str] = []
    lock = threading.Lock()

    def by(name: str):
        def activate(request: ActivateRequestV1) -> ActivateReplyV1:
            with lock:
                answered.append(name)
            return ActivateReplyV1()

        return activate

    try:
        server.serve(PROFILE_ACTIVATE, by("eins"), queue="scoring")
        second.serve(PROFILE_ACTIVATE, by("zwei"), queue="scoring")
        for _ in range(6):
            assert (
                client.call(PROFILE_ACTIVATE, ActivateRequestV1(profile_id=1, version=2)).error
                is None
            )
    finally:
        second.close()
    assert len(answered) == 6
