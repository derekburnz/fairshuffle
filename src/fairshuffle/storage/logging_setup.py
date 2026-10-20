"""Rotating log files with every secret masked before a line is written.

Sign-in and Spotify calls (Phase 2) handle access tokens, refresh tokens, authorization codes and
the Client ID. Any of them could end up in a log line by accident, for example inside a URL or an
error message, so every record passes through RedactingFilter on its way to the file. Tracebacks
are masked too, because exception messages often quote the request that failed. The user's home
folder is written as %USERPROFILE%, because its path contains the Windows user name and log files
may be attached to bug reports.

The filter fails closed: when in doubt it masks. "exit code=0" loses its 0, which is a fair price
for never writing a real code=.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePath
from types import TracebackType

from fairshuffle.storage.paths import log_dir

LOG_FILE_NAME = "fairshuffle.log"
MAX_BYTES = 1_000_000  # about 1 MB per file
BACKUP_COUNT = 5  # fairshuffle.log plus .1 to .5, so at most about 6 MB in all
MASK = "[REDACTED]"
HOME_MASK = "%USERPROFILE%"

# A key whose value is a secret: anything ending in token, secret, verifier or client_id (so
# new_access_token and id_token count too), or exactly "code". code needs the whole word, so
# error_code and postcode stay readable. state is left alone: it is a one-time nonce that only
# guards a single sign-in, and seeing it helps when debugging one.
_KEY = r"(?:[a-z0-9_]*(?:token|secret|verifier|client_id)|code)"
_SECRET_FIELD = re.compile(
    rf"""(?ix)
    (?<![a-z0-9_])
    (?P<key>{_KEY}["']?\s*[:=]\s*)        # access_token=  "access_token": access_token :
    (?!["']?{re.escape(MASK)})              # already masked, so running redact twice is harmless
    (?:
        # A quoted value, \" included. A backslash only ever goes through the \\. branch, so a
        # long run of them can be read one way only (two overlapping ways would take exponential
        # time when the closing quote is missing).
        (?P<quote>["'])(?:\\.|(?!(?P=quote))[^\\\n])*(?P=quote)
        # A quoted value cut off before its closing quote: mask up to the next delimiter.
      | (?P<open>["'])[^\s"',;)}}\]]*
        # A bare value, up to a delimiter.
      | [^\s"'&,;)}}\]]+
    )
    """
)
# The whole value of an Authorization header, whatever the scheme (Bearer, Basic or anything).
_AUTHORIZATION = re.compile(r"""(?i)\b(?P<key>authorization["']?\s*[:=]\s*["']?)[^\r\n"',}]+""")
# A Bearer token on its own, without the header name.
_BEARER = re.compile(r"(?i)\b(?P<key>bearer\s+)[a-z0-9\-._~+/]+=*")


def _keep_key(match: re.Match[str]) -> str:
    """Keep the key (and any quotes around the value) so the line still reads well."""
    groups = match.groupdict()
    quote = groups.get("quote") or ""
    return f"{match['key']}{quote or groups.get('open') or ''}{MASK}{quote}"


def redact(text: str, secrets: Iterable[str] = (), home: PurePath | None = None) -> str:
    """Mask every secret in text: secret fields, Authorization values and the given exact values.

    If home is given, that folder's path is written as %USERPROFILE%, in any letter case and with
    either kind of slash.
    """
    for pattern in (_AUTHORIZATION, _BEARER, _SECRET_FIELD):
        text = pattern.sub(_keep_key, text)
    for value in secrets:
        if value:
            text = text.replace(value, MASK)
    if home is not None and (home_pattern := _home_pattern(home)) is not None:
        text = home_pattern.sub(HOME_MASK, text)
    return text


def _home_pattern(home: PurePath) -> re.Pattern[str] | None:
    """Match the home path the way Windows treats it: any case, \\ or / (doubled in a repr)."""
    if len(home.parts) < 2:
        return None  # a bare root such as "/" would match every path
    pieces = [re.escape(part.rstrip("\\/")) for part in home.parts]
    # The lookahead stops C:\Users\derek from matching inside C:\Users\derek2.
    return re.compile(r"[\\/]+".join(pieces) + r"(?![\w.-])", re.IGNORECASE)


class RedactingFilter(logging.Filter):
    """Masks secrets and the home folder in each record before any handler writes it."""

    def __init__(self, secrets: Iterable[str] = (), home: PurePath | None = None) -> None:
        super().__init__()
        self._secrets = {value for value in secrets if value}
        self._home: PurePath = home or Path.home()

    def add_secret(self, value: str) -> None:
        """Also mask this exact value from now on."""
        if value:
            self._secrets.add(value)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # A bad format call must not turn a log line into a crash. The arguments are left
            # out, because a secret among them would have no field name to be caught by.
            message = f"{record.msg} [log arguments did not fit the message]"
        record.msg = redact(message, self._secrets, self._home)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets, self._home)
        if record.stack_info:
            record.stack_info = redact(record.stack_info, self._secrets, self._home)
        return True


class _FairShuffleHandler(RotatingFileHandler):
    """Marks the handler setup_logging installed, so a second call replaces it."""


_installed_filter: RedactingFilter | None = None
_masked_values: set[str] = set()  # kept across setup_logging calls, so call order never matters


def setup_logging(
    directory: Path | None = None,
    *,
    secrets: Iterable[str] = (),
    home: PurePath | None = None,
    level: int = logging.INFO,
    max_bytes: int = MAX_BYTES,
) -> None:
    """Send all log records to a rotating file in directory (the logs folder by default).

    home is the folder to write as %USERPROFILE% (the user's home folder by default).
    """
    global _installed_filter
    directory = directory or log_dir()
    directory.mkdir(parents=True, exist_ok=True)

    # delay=True opens the file at the first line, so a second copy that only hands over to the
    # running one never opens it (two processes holding the file can break a rollover on Windows).
    handler = _FairShuffleHandler(
        directory / LOG_FILE_NAME,
        maxBytes=max_bytes,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _masked_values.update(value for value in secrets if value)
    _installed_filter = RedactingFilter(_masked_values, home)
    handler.addFilter(_installed_filter)

    root = logging.getLogger()
    _remove_handlers(root)
    root.addHandler(handler)
    root.setLevel(level)

    # The packaged app has no console, so a crash would vanish without a trace. Log it instead.
    sys.excepthook = _log_uncaught_exception


def mask_secret(value: str) -> None:
    """Mask this exact value in every later log line, whether or not logging has started yet.

    Call it as soon as a secret is known: the settings loader with the Client ID it reads from
    .env (M2), sign-in with each token it receives. The field patterns already catch tokens in
    their usual shapes; this also catches them anywhere else.
    """
    if not value:
        return
    _masked_values.add(value)
    if _installed_filter is not None:
        _installed_filter.add_secret(value)


def stop_logging() -> None:
    """Undo setup_logging: close the log file and give crash reports back to Python."""
    global _installed_filter
    _installed_filter = None
    _remove_handlers(logging.getLogger())
    if sys.excepthook is _log_uncaught_exception:
        sys.excepthook = sys.__excepthook__


def _remove_handlers(root: logging.Logger) -> None:
    for handler in [h for h in root.handlers if isinstance(h, _FairShuffleHandler)]:
        root.removeHandler(handler)
        handler.close()


def _log_uncaught_exception(
    exc_type: type[BaseException], exc: BaseException, traceback: TracebackType | None
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, traceback)
        return
    logging.getLogger("fairshuffle").critical(
        "Unexpected error", exc_info=(exc_type, exc, traceback)
    )
