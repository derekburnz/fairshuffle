"""A one-shot web listener on 127.0.0.1 that catches Spotify's sign-in callback.

After the user approves FairShuffle in the browser, Spotify sends the browser to the Redirect URI,
http://127.0.0.1:8888/callback, with a one-time authorization code and the state value in the
query string. This module is the tiny web server on the other end of that address.

It is deliberately small, because it is the only part of FairShuffle that accepts connections:

- It binds to 127.0.0.1 only, never 0.0.0.0, so nothing outside this PC can reach it. On Windows
  it also claims the port exclusively, so no other program can bind the same port and answer in
  its place.
- It answers on the Redirect URI's path and nowhere else, and serves no files.
- It checks state before it looks at anything else, in constant time (pkce.states_match).
- It stops after the first callback, whatever that callback held, or when the time runs out.
- It never logs a request line, because the query string holds the authorization code.

Construct the listener before opening the browser, so the port is already held when Spotify
redirects, then call wait() from a worker thread. cancel() may be called from any thread.
"""

from __future__ import annotations

import contextlib
import logging
import re
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from types import TracebackType
from typing import cast
from urllib.parse import parse_qs, urlsplit

from fairshuffle.auth.pkce import states_match

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_TIMEOUT_SECONDS = 300.0  # five minutes to finish signing in, then give up
POLL_SECONDS = 0.25  # how often wait() checks for cancel() and the deadline
CONNECTION_TIMEOUT_SECONDS = 5.0  # a browser that connects but sends nothing is dropped

log = logging.getLogger(__name__)

# Spotify's error values are short snake_case words such as access_denied. Anything else is not
# repeated in an error message, because the callback's query comes from outside the app.
_ERROR_VALUE = re.compile(r"[a-z_]{1,64}")


class InvalidRedirectUri(ValueError):
    """The Redirect URI is not one this listener can serve. The message says why."""


class CallbackError(Exception):
    """Sign-in did not produce an authorization code. Subclasses say why."""


class PortInUse(CallbackError):
    """Another program is using the Redirect URI's port."""


class StateMismatch(CallbackError):
    """The callback's state was missing or wrong, so it did not come from this sign-in."""


class SignInDenied(CallbackError):
    """Spotify sent an error instead of a code, for example access_denied when the user cancels."""

    def __init__(self, error: str) -> None:
        super().__init__(f"Spotify did not sign in: {error}")
        self.error = error


class MissingCode(CallbackError):
    """The callback had the right state but no single authorization code."""


class CallbackTimeout(CallbackError):
    """No callback arrived before the time ran out."""


class ListenerCancelled(CallbackError):
    """cancel() was called before a callback arrived."""


@dataclass(frozen=True, slots=True)
class RedirectTarget:
    """The port and path the listener serves. The host is always 127.0.0.1."""

    port: int
    path: str

    @classmethod
    def parse(cls, uri: str) -> RedirectTarget:
        """Read a Redirect URI such as http://127.0.0.1:8888/callback, refusing anything unsafe."""
        parts = urlsplit(uri)
        if parts.scheme != "http":
            raise InvalidRedirectUri("The Redirect URI must start with http:// (loopback only).")
        if parts.hostname != LOOPBACK_HOST:
            raise InvalidRedirectUri(
                "The Redirect URI must use 127.0.0.1. Spotify does not allow localhost."
            )
        if parts.username is not None or parts.password is not None:
            raise InvalidRedirectUri("The Redirect URI must not hold a user name or password.")
        try:
            port = parts.port
        except ValueError:
            port = None
        if port is None or port == 0:
            raise InvalidRedirectUri("The Redirect URI needs a port from 1 to 65535, such as 8888.")
        if parts.query or parts.fragment:
            raise InvalidRedirectUri("The Redirect URI must not have a query (?) or fragment (#).")
        return cls(port=port, path=parts.path or "/")


_SUCCESS_PAGE = "Signed in to FairShuffle. You can close this tab and go back to the tray icon."
_DENIED_PAGE = "FairShuffle is not signed in. You can close this tab."
_REJECTED_PAGE = (
    "This sign-in link did not come from FairShuffle, so it was ignored. "
    "Start signing in again from the FairShuffle tray icon."
)
_NOT_FOUND_PAGE = "Not found."
_UNREADABLE_PAGE = "FairShuffle could not read that request."


def _page(message: str) -> bytes:
    """A plain page with no scripts, styles, links or images, so it can't leak the code onward."""
    return (
        "<!doctype html><html lang=en><meta charset=utf-8><title>FairShuffle</title>"
        f"<p>{message}</p></html>"
    ).encode()


def _single(query: dict[str, list[str]], name: str) -> str | None:
    """The value of name if it appears exactly once, else None."""
    values = query.get(name, [])
    return values[0] if len(values) == 1 else None


class _CallbackServer(socketserver.TCPServer):
    allow_reuse_address = False  # SO_REUSEADDR would let another socket share the port

    def __init__(self, port: int, listener: LoopbackListener) -> None:
        self.listener = listener
        super().__init__((LOOPBACK_HOST, port), _CallbackHandler)

    def server_bind(self) -> None:
        # Windows only: refuse to share the port with any other socket, even one that asks.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def handle_error(self, request: object, client_address: object) -> None:
        error = sys.exception()
        if isinstance(error, ConnectionError):  # the browser, or a hang-up, closed it first
            log.info("A sign-in connection closed before its answer was sent")
            return
        log.exception("The sign-in listener could not answer a request")


class _CallbackHandler(BaseHTTPRequestHandler):
    timeout = CONNECTION_TIMEOUT_SECONDS
    server_version = "FairShuffle"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        # timeout limits each read. This limits the whole connection, so a client that trickles
        # in one byte at a time can't keep the listener busy and hold off cancel() or the deadline.
        # The lock makes sure the hang-up never touches the socket once finish() has begun, since
        # the server closes it right after.
        self._lock = threading.Lock()
        self._open = True
        self._dropped = threading.Event()
        self._hang_up = threading.Timer(self.timeout or CONNECTION_TIMEOUT_SECONDS, self._drop)
        self._hang_up.daemon = True
        self._hang_up.start()

    def finish(self) -> None:
        with self._lock:
            self._open = False
        self._hang_up.cancel()
        super().finish()

    def _drop(self) -> None:
        with self._lock:
            if not self._open:
                return
            self._dropped.set()
            with contextlib.suppress(OSError):
                self.connection.shutdown(socket.SHUT_RDWR)
        log.info("Hung up on a sign-in connection that took too long to send its request")

    def parse_request(self) -> bool:
        # After a hang-up, reading stops part way and whatever arrived would look like a whole
        # request. It isn't one, so it is thrown away unanswered.
        if self._dropped.is_set():
            self.close_connection = True
            return False
        accepted = super().parse_request()
        if self._dropped.is_set():
            self.close_connection = True
            return False
        return accepted

    def do_GET(self) -> None:
        # A full URL (GET http://host/callback) is not what a browser sends to this address.
        # Checking first also keeps urlsplit away from hosts it can't read, such as [text].
        if not self.path.startswith("/"):
            self._reply(HTTPStatus.NOT_FOUND, _NOT_FOUND_PAGE)
            return
        parts = urlsplit(self.path)
        listener = cast(_CallbackServer, self.server).listener
        if parts.path != listener.target.path:
            self._reply(HTTPStatus.NOT_FOUND, _NOT_FOUND_PAGE)
            return
        outcome = listener._accept(parse_qs(parts.query, keep_blank_values=True))
        if isinstance(outcome, str):
            self._reply(HTTPStatus.OK, _SUCCESS_PAGE)
        elif isinstance(outcome, SignInDenied):
            self._reply(HTTPStatus.OK, _DENIED_PAGE)
        else:
            self._reply(HTTPStatus.BAD_REQUEST, _REJECTED_PAGE)

    def _reply(self, status: HTTPStatus, message: str) -> None:
        body = _page(message)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer requests http.server rejects itself (bad syntax, POST) with the same plain page.

        The standard error page would repeat part of the request, and the request line can hold
        the authorization code.
        """
        self.close_connection = True
        self._reply(HTTPStatus(code), _UNREADABLE_PAGE)

    def log_message(self, format: str, *args: object) -> None:
        """Log nothing: the standard request log line would quote the authorization code."""


class LoopbackListener:
    """Waits for one sign-in callback on 127.0.0.1 and returns its authorization code.

    Binding happens in the constructor, so create the listener before opening the browser.
    Use it as a context manager so the port is always released.
    """

    def __init__(self, target: RedirectTarget, expected_state: str) -> None:
        self.target = target
        self._expected_state = expected_state
        self._outcome: str | CallbackError | None = None
        self._cancelled = threading.Event()
        self._used = False
        try:
            self._server = _CallbackServer(target.port, self)
        except OSError as error:
            raise PortInUse(
                f"Port {target.port} on 127.0.0.1 is in use, so sign-in can't listen for "
                "Spotify's reply. If you just tried to sign in, wait a minute and try again "
                "(Windows holds the port briefly after each try). Otherwise another program "
                "has it: close that program or pick another port in both .env and the Spotify "
                "dashboard."
            ) from error
        self._server.timeout = POLL_SECONDS
        log.info("Sign-in listener ready on 127.0.0.1 port %d", self.port)

    @property
    def address(self) -> tuple[str, int]:
        """The address the socket is bound to, read back from the socket itself."""
        host, port = self._server.socket.getsockname()[:2]
        return host, port

    @property
    def port(self) -> int:
        return self.address[1]

    def wait(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
        """Block until one callback arrives, then return its authorization code.

        Raises a CallbackError subclass if the callback is not a valid answer to this sign-in,
        if cancel() is called or if timeout seconds pass. The listener closes either way and
        can't be used again.
        """
        if self._used:
            raise RuntimeError("A LoopbackListener answers one sign-in only; make a new one.")
        self._used = True
        deadline = time.monotonic() + timeout
        try:
            while self._outcome is None:
                if self._cancelled.is_set():
                    raise ListenerCancelled("Sign-in was cancelled.")
                if time.monotonic() >= deadline:
                    raise CallbackTimeout("Spotify did not answer in time. Try signing in again.")
                self._server.handle_request()
        finally:
            self.close()
        if isinstance(self._outcome, CallbackError):
            raise self._outcome
        return self._outcome

    def cancel(self) -> None:
        """Make wait() give up. Safe to call from any thread.

        It takes effect within POLL_SECONDS. If a request is being read at that moment it can take
        up to CONNECTION_TIMEOUT_SECONDS, or about twice that on Windows, where hanging up does
        not always wake a read that is already waiting.
        """
        self._cancelled.set()

    def close(self) -> None:
        """Release the port. Safe to call more than once."""
        self._server.server_close()

    def __enter__(self) -> LoopbackListener:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _accept(self, query: dict[str, list[str]]) -> str | CallbackError:
        """Judge the one callback this listener takes. Called by the handler."""
        if not states_match(self._expected_state, _single(query, "state")):
            log.warning("Ignored a sign-in callback with a missing or wrong state")
            outcome: str | CallbackError = StateMismatch(
                "The sign-in reply did not match this sign-in. Try signing in again."
            )
        elif "error" in query:
            error = _single(query, "error") or ""
            shown = error if _ERROR_VALUE.fullmatch(error) else "unknown"
            log.info("Spotify answered the sign-in with an error: %s", shown)
            outcome = SignInDenied(shown)
        elif code := _single(query, "code"):
            log.info("Sign-in callback received")
            outcome = code
        else:
            log.warning("A sign-in callback had the right state but no single code")
            outcome = MissingCode("Spotify's reply had no sign-in code. Try signing in again.")
        self._outcome = outcome
        return outcome
