"""The sign-in listener, driven by a real HTTP client over 127.0.0.1.

Each test binds port 0, so the operating system picks a free port and tests never collide with
each other or with a FairShuffle copy the developer has running.
"""

from __future__ import annotations

import contextlib
import http.client
import logging
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlencode

import pytest

from fairshuffle.auth import loopback
from fairshuffle.auth.loopback import (
    CallbackTimeout,
    ListenerCancelled,
    LoopbackListener,
    MissingCode,
    PortInUse,
    RedirectTarget,
    SignInDenied,
    StateMismatch,
)

STATE = "fake-state-for-tests-0123456789abcdefghijklm"
CODE = "fake-auth-code-for-tests"
ANY_PORT = RedirectTarget(port=0, path="/callback")


@dataclass
class Reply:
    status: int
    headers: http.client.HTTPMessage
    body: str


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check for cancel() and the deadline often, so the tests stay quick."""
    monkeypatch.setattr(loopback, "POLL_SECONDS", 0.02)


@pytest.fixture
def pool() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        yield executor


def get(port: int, path: str, method: str = "GET") -> Reply:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return Reply(response.status, response.headers, response.read().decode())
    finally:
        connection.close()


def callback(**query: str) -> str:
    return "/callback?" + urlencode(query)


def start(pool: ThreadPoolExecutor, listener: LoopbackListener) -> Future[str]:
    return pool.submit(listener.wait, 5)


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def test_listens_on_127_0_0_1_only() -> None:
    with LoopbackListener(ANY_PORT, STATE) as listener:
        host, port = listener.address

    assert host == "127.0.0.1"
    assert port > 0


def test_a_good_callback_returns_the_code(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE
    assert reply.status == 200
    assert "You can close this tab" in reply.body


def test_the_reply_page_is_locked_down(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(code=CODE, state=STATE))
    result.result()

    assert reply.headers["Content-Type"] == "text/html; charset=utf-8"
    assert reply.headers["Cache-Control"] == "no-store"
    assert reply.headers["Referrer-Policy"] == "no-referrer"
    assert reply.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert reply.headers["X-Content-Type-Options"] == "nosniff"
    assert reply.headers["Server"].startswith("FairShuffle")
    assert "Python" not in reply.headers["Server"]
    assert CODE not in reply.body
    assert "<script" not in reply.body
    assert "href" not in reply.body


@pytest.mark.parametrize(
    "query",
    [
        {"code": CODE, "state": "wrong-state"},
        {"code": CODE},
        {"code": CODE, "state": ""},
        {"error": "access_denied", "state": "wrong-state"},
    ],
)
def test_a_wrong_or_missing_state_is_rejected(
    pool: ThreadPoolExecutor, query: dict[str, str]
) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(**query))

    with pytest.raises(StateMismatch):
        result.result()
    assert reply.status == 400
    assert "did not come from FairShuffle" in reply.body


def test_a_repeated_state_is_rejected(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    get(listener.port, f"/callback?code={CODE}&state={STATE}&state={STATE}")

    with pytest.raises(StateMismatch):
        result.result()


def test_cancelling_in_spotify_is_reported(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(error="access_denied", state=STATE))

    with pytest.raises(SignInDenied) as caught:
        result.result()
    assert caught.value.error == "access_denied"
    assert reply.status == 200
    assert "not signed in" in reply.body


@pytest.mark.parametrize("error", ["<script>alert(1)</script>", "", "Access Denied", "x" * 65])
def test_an_odd_error_value_is_not_repeated(pool: ThreadPoolExecutor, error: str) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(error=error, state=STATE))

    with pytest.raises(SignInDenied) as caught:
        result.result()
    assert caught.value.error == "unknown"
    assert "<script>alert" not in reply.body


@pytest.mark.parametrize(
    "path",
    [
        callback(state=STATE),
        callback(code="", state=STATE),
        f"/callback?code=one&code=two&state={STATE}",
    ],
)
def test_no_single_code_is_rejected(pool: ThreadPoolExecutor, path: str) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, path)

    with pytest.raises(MissingCode):
        result.result()
    assert reply.status == 400


def test_other_paths_get_404_and_the_listener_keeps_waiting(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    favicon = get(listener.port, "/favicon.ico")
    elsewhere = get(listener.port, "/callback/../etc?" + urlencode({"code": CODE, "state": STATE}))
    other_method = get(listener.port, callback(code=CODE, state=STATE), method="POST")
    assert not result.done()

    get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE
    assert favicon.status == 404
    assert elsewhere.status == 404
    assert other_method.status == 501


def test_it_stops_after_one_callback(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    port = listener.port
    result = start(pool, listener)

    get(port, callback(code="wrong", state="wrong-state"))

    with pytest.raises(StateMismatch):
        result.result()
    assert port_is_free(port)


def test_it_stops_after_the_timeout() -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    port = listener.port
    started = time.monotonic()

    with pytest.raises(CallbackTimeout):
        listener.wait(timeout=0.1)

    assert time.monotonic() - started < 2
    assert port_is_free(port)


def test_cancel_from_another_thread_stops_it(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    listener.cancel()

    with pytest.raises(ListenerCancelled):
        result.result(timeout=5)


def test_a_silent_connection_does_not_block_sign_in(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loopback._CallbackHandler, "timeout", 0.1)
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    with socket.create_connection(("127.0.0.1", listener.port)):  # connects, then says nothing
        time.sleep(0.3)
    get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE


def test_a_trickling_connection_is_dropped(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loopback._CallbackHandler, "timeout", 0.2)
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)
    started = time.monotonic()

    # The listener hangs up part way, so a later send fails with an OSError.
    with (
        socket.create_connection(("127.0.0.1", listener.port)) as slow,
        contextlib.suppress(OSError),
    ):
        while time.monotonic() - started < 5:
            slow.sendall(b"G")  # never a whole request line
            time.sleep(0.02)
    dropped_after = time.monotonic() - started
    get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE
    assert dropped_after < 3


@pytest.mark.parametrize(
    "cut_off",
    [
        f"GET /callback?code=early-code&state={STATE}",  # no end of line yet
        f"GET /callback?code=early-code&state={STATE} HTTP/1.1\r\nHost: 127.0.0.1",
    ],
)
def test_a_request_cut_off_by_the_hang_up_is_thrown_away(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch, cut_off: str
) -> None:
    monkeypatch.setattr(loopback._CallbackHandler, "timeout", 0.2)
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    with socket.create_connection(("127.0.0.1", listener.port)) as slow:
        slow.sendall(cut_off.encode())
        slow.settimeout(5)
        with contextlib.suppress(OSError):
            assert slow.recv(4096) == b""  # hung up on, with no answer
    assert not result.done()
    get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE


def test_a_hang_up_that_fires_after_the_reply_does_nothing(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Timer.cancel() can't stop a hang-up that has already begun, so it must check for itself."""
    hang_ups: list[Callable[[], None]] = []

    class PausedTimer:
        daemon = False

        def __init__(self, _interval: float, function: Callable[[], None]) -> None:
            hang_ups.append(function)

        def start(self) -> None: ...

        def cancel(self) -> None: ...

    monkeypatch.setattr(threading, "Timer", PausedTimer)
    caplog.set_level(logging.INFO)
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)
    get(listener.port, callback(code=CODE, state=STATE))
    assert result.result() == CODE

    hang_ups[0]()  # fires late, after finish()

    assert "Hung up" not in caplog.text


def raw(port: int, request: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(request)
        chunks = []
        while chunk := connection.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.parametrize(
    ("request_bytes", "status"),
    [
        # Rejected on the request line, so nothing more is sent: unread bytes left behind
        # when the listener hangs up would make it reset the connection instead.
        (f"NONSENSE /callback?code={CODE}\r\n".encode(), b"400"),
        (f"GET /callback?code={CODE}&state={STATE} HTTP/9.9\r\n".encode(), b"505"),
        (f"POST /callback?code={CODE}&state={STATE} HTTP/1.1\r\n\r\n".encode(), b"501"),
    ],
)
def test_requests_http_server_rejects_get_the_plain_page(
    pool: ThreadPoolExecutor, request_bytes: bytes, status: bytes
) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = raw(listener.port, request_bytes)
    listener.cancel()

    with pytest.raises(ListenerCancelled):
        result.result()
    assert reply.split(b" ")[1] == status
    assert b"could not read that request" in reply
    assert b"Content-Security-Policy: default-src 'none'" in reply
    assert CODE.encode() not in reply


def test_head_gets_headers_only(pool: ThreadPoolExecutor) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = get(listener.port, callback(code=CODE, state=STATE), method="HEAD")
    listener.cancel()

    with pytest.raises(ListenerCancelled):
        result.result()
    assert reply.status == 501
    assert reply.body == ""


@pytest.mark.parametrize("host", ["elsewhere", "[text]"])
def test_a_full_url_in_the_request_line_is_not_the_callback(
    pool: ThreadPoolExecutor, caplog: pytest.LogCaptureFixture, host: str
) -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    reply = raw(
        listener.port,
        f"GET http://{host}{callback(code=CODE, state=STATE)} HTTP/1.0\r\n\r\n".encode(),
    )
    assert not result.done()
    get(listener.port, callback(code=CODE, state=STATE))

    assert result.result() == CODE
    assert reply.split(b" ")[1] == b"404"
    assert "could not answer" not in caplog.text


def test_it_can_be_used_once_only() -> None:
    listener = LoopbackListener(ANY_PORT, STATE)
    with pytest.raises(CallbackTimeout):
        listener.wait(timeout=0)

    with pytest.raises(RuntimeError, match="one sign-in only"):
        listener.wait()


def test_leaving_the_with_block_frees_the_port() -> None:
    with LoopbackListener(ANY_PORT, STATE) as listener:
        port = listener.port
        assert not port_is_free(port)

    assert port_is_free(port)


def test_a_busy_port_gives_a_clear_error() -> None:
    with socket.socket() as other_program:
        other_program.bind(("127.0.0.1", 0))
        other_program.listen()
        busy = other_program.getsockname()[1]

        with pytest.raises(PortInUse, match=f"Port {busy} on 127.0.0.1 is in use"):
            LoopbackListener(RedirectTarget(port=busy, path="/callback"), STATE)


@pytest.mark.skipif(sys.platform != "win32", reason="SO_EXCLUSIVEADDRUSE is Windows only")
def test_on_windows_the_port_is_claimed_exclusively() -> None:
    with LoopbackListener(ANY_PORT, STATE) as listener:
        server_socket = listener._server.socket
        option = socket.SO_EXCLUSIVEADDRUSE  # type: ignore[attr-defined]

        assert server_socket.getsockopt(socket.SOL_SOCKET, option) == 1


def test_without_exclusive_ports_it_still_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(socket, "SO_EXCLUSIVEADDRUSE", raising=False)

    with LoopbackListener(ANY_PORT, STATE) as listener:
        assert listener.address[0] == "127.0.0.1"


def test_a_handler_failure_is_logged_and_waiting_goes_on(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*_args: object) -> object:
        raise OSError("fake failure")

    listener = LoopbackListener(ANY_PORT, STATE)
    monkeypatch.setattr(listener, "_accept", broken)
    result = start(pool, listener)

    with pytest.raises((http.client.HTTPException, OSError)):
        get(listener.port, callback(code=CODE, state=STATE))
    listener.cancel()

    with pytest.raises(ListenerCancelled):
        result.result()
    assert "could not answer a request" in caplog.text


def test_a_connection_closed_early_is_noted_without_a_traceback(
    pool: ThreadPoolExecutor, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def closed(*_args: object) -> object:
        raise BrokenPipeError("fake closed connection")

    caplog.set_level(logging.INFO)
    listener = LoopbackListener(ANY_PORT, STATE)
    monkeypatch.setattr(listener, "_accept", closed)
    result = start(pool, listener)

    with pytest.raises((http.client.HTTPException, OSError)):
        get(listener.port, callback(code=CODE, state=STATE))
    listener.cancel()

    with pytest.raises(ListenerCancelled):
        result.result()
    assert "closed before its answer was sent" in caplog.text
    assert "could not answer" not in caplog.text
    assert "Traceback" not in caplog.text


def test_the_code_and_state_never_reach_the_logs_or_console(
    pool: ThreadPoolExecutor, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    listener = LoopbackListener(ANY_PORT, STATE)
    result = start(pool, listener)

    get(listener.port, "/favicon.ico")
    get(listener.port, callback(code=CODE, state=STATE))
    result.result()

    console = capsys.readouterr()
    for text in (caplog.text, console.out, console.err):
        assert CODE not in text
        assert STATE not in text
    assert "Sign-in callback received" in caplog.text
