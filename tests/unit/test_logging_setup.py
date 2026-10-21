"""Log redaction: fake secrets go in, and none of them may reach the log file."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from fairshuffle.storage import logging_setup
from fairshuffle.storage.logging_setup import (
    HOME_MASK,
    LOG_FILE_NAME,
    MASK,
    RedactingFilter,
    mask_secret,
    redact,
    setup_logging,
    stop_logging,
)

FAKE_CLIENT_ID = "fake-client-id-for-tests"
FAKE_ACCESS = "fake-access-value-1234"
FAKE_REFRESH = "fake-refresh-value-5678"
FAKE_CODE = "fake-auth-code-9012"
FAKE_VERIFIER = "fake-verifier-3456"
ALL_FAKES = (FAKE_CLIENT_ID, FAKE_ACCESS, FAKE_REFRESH, FAKE_CODE, FAKE_VERIFIER)
FAKE_HOME = PureWindowsPath("C:/Users/fake-user")


@pytest.fixture
def log_file(tmp_path: Path) -> Iterator[Path]:
    """Log to a temporary folder, then take the handler and the crash hook back out."""
    setup_logging(tmp_path, secrets=[FAKE_CLIENT_ID], home=FAKE_HOME)
    yield tmp_path / LOG_FILE_NAME
    stop_logging()


def read_log(path: Path) -> str:
    """The log so far. The file only appears with the first line, so no file means no lines."""
    for handler in logging.getLogger().handlers:
        handler.flush()
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        (f"Authorization: Bearer {FAKE_ACCESS}", "Authorization: "),
        (f"Authorization: Basic {FAKE_ACCESS}", "Authorization: "),
        (f"{{'Authorization': 'Bearer {FAKE_ACCESS}', 'Accept': 'json'}}", "'Accept': 'json'"),
        (f"retrying with Bearer {FAKE_ACCESS} now", "Bearer "),
        (f"GET http://127.0.0.1:8888/callback?code={FAKE_CODE}&state=abc", "state=abc"),
        (
            f"grant_type=refresh_token&refresh_token={FAKE_REFRESH}&client_id={FAKE_CLIENT_ID}",
            "grant_type=refresh_token",
        ),
        (f'{{"access_token": "{FAKE_ACCESS}", "expires_in": 3600}}', '"expires_in": 3600'),
        (f"{{'refresh_token': '{FAKE_REFRESH}'}}", "'refresh_token': "),
        (f"code_verifier={FAKE_VERIFIER}", "code_verifier="),
        # The repr a dataclass or attrs class gives, with either kind of quote.
        (
            f"Token(access_token='{FAKE_ACCESS}', "
            f'refresh_token="{FAKE_REFRESH}", expires_in=3600)',
            "expires_in=3600",
        ),
        # Upper and mixed case names.
        (f"ACCESS_TOKEN={FAKE_ACCESS}&Refresh_Token={FAKE_REFRESH}&Code={FAKE_CODE}", "Code="),
        # Spaces or a colon around the value.
        (f"access_token = {FAKE_ACCESS}, refresh_token: {FAKE_REFRESH}", "refresh_token: "),
        # A prefix in front of the name.
        (f"new_access_token={FAKE_ACCESS} id_token={FAKE_REFRESH}", "id_token="),
        # An escaped quote inside a JSON value.
        (f'{{"code": "ab\\"{FAKE_CODE}", "state": "s"}}', '"state": "s"'),
    ],
)
def test_redact_masks_secret_fields_and_keeps_the_rest(text: str, kept: str) -> None:
    masked = redact(text)

    assert MASK in masked
    assert kept in masked
    for fake in ALL_FAKES:
        assert fake not in masked


def test_redact_masks_exact_values_anywhere() -> None:
    masked = redact(f"Using app {FAKE_CLIENT_ID} now", secrets=[FAKE_CLIENT_ID])

    assert masked == f"Using app {MASK} now"


def test_redact_leaves_similar_names_alone() -> None:
    text = "error_code=429 and postcode=K1A for grant_type=authorization_code&state=abc"

    assert redact(text) == text


def test_redacting_twice_changes_nothing_more() -> None:
    once = redact(f"code={FAKE_CODE} access_token='{FAKE_ACCESS}' Authorization: Bearer x")

    assert redact(once) == once


def test_a_bad_format_call_is_logged_without_its_arguments() -> None:
    record = logging.LogRecord(
        "fairshuffle.test", logging.INFO, __file__, 1, "Got %s and %s", (FAKE_ACCESS,), None
    )

    logging_setup.RedactingFilter().filter(record)

    assert record.getMessage() == "Got %s and %s [log arguments did not fit the message]"


def test_no_fake_secret_reaches_the_log_file(log_file: Path) -> None:
    log = logging.getLogger("fairshuffle.test")
    log.info("Exchanging code=%s with verifier %s", FAKE_CODE, f"code_verifier={FAKE_VERIFIER}")
    log.info("Token response: %s", {"access_token": FAKE_ACCESS, "refresh_token": FAKE_REFRESH})
    log.warning("Header was Bearer %s", FAKE_ACCESS)
    log.info("Signed in to app %s", FAKE_CLIENT_ID)
    try:
        raise RuntimeError(f"401 for https://api.spotify.com/v1/me?access_token={FAKE_ACCESS}")
    except RuntimeError:
        log.exception("Request failed")
    log.info("stack check", stack_info=True)

    text = read_log(log_file)

    for fake in ALL_FAKES:
        assert fake not in text
    assert text.count(MASK) >= 7
    assert "Request failed" in text
    assert "RuntimeError: 401 for https://api.spotify.com/v1/me?access_token=" in text


def test_secrets_learned_later_are_masked_too(log_file: Path) -> None:
    mask_secret("fake-late-client-id")

    logging.getLogger("fairshuffle.test").info("Client fake-late-client-id")

    assert "fake-late-client-id" not in read_log(log_file)


def test_setting_up_twice_keeps_one_file_handler(tmp_path: Path, log_file: Path) -> None:
    setup_logging(tmp_path)

    handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, logging_setup._FairShuffleHandler)
    ]
    assert len(handlers) == 1


def test_log_files_rotate_and_old_ones_are_kept(tmp_path: Path, log_file: Path) -> None:
    setup_logging(tmp_path, max_bytes=500)
    log = logging.getLogger("fairshuffle.test")

    for line in range(100):
        log.info("line %d %s", line, "x" * 40)
    read_log(log_file)

    rotated = sorted(p.name for p in tmp_path.iterdir() if p.name != LOG_FILE_NAME)
    assert rotated == [f"{LOG_FILE_NAME}.{n}" for n in range(1, logging_setup.BACKUP_COUNT + 1)]


def test_uncaught_errors_are_logged_with_secrets_masked(log_file: Path) -> None:
    try:
        raise ValueError(f"refresh_token={FAKE_REFRESH} rejected")
    except ValueError as error:
        sys.excepthook(type(error), error, error.__traceback__)

    text = read_log(log_file)
    assert "CRITICAL fairshuffle: Unexpected error" in text
    assert "ValueError: refresh_token=[REDACTED] rejected" in text
    assert FAKE_REFRESH not in text


def test_keyboard_interrupt_is_left_to_python(
    log_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[type[BaseException]] = []
    monkeypatch.setattr(sys, "__excepthook__", lambda exc_type, *_: seen.append(exc_type))

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert seen == [KeyboardInterrupt]
    assert "Unexpected error" not in read_log(log_file)


def test_empty_secrets_are_ignored() -> None:
    redacting_filter = logging_setup.RedactingFilter(secrets=["", FAKE_CLIENT_ID])
    redacting_filter.add_secret("")
    record = logging.LogRecord(
        "fairshuffle.test", logging.INFO, __file__, 1, "plain text", None, None
    )

    redacting_filter.filter(record)

    # Masking "" would put the mask between every character.
    assert record.getMessage() == "plain text"
    assert redact("plain text", secrets=[""]) == "plain text"
    mask_secret("")
    assert "" not in logging_setup._masked_values


def test_filter_masks_a_traceback_no_handler_has_formatted_yet() -> None:
    try:
        raise RuntimeError(f"code={FAKE_CODE}")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "fairshuffle.test", logging.ERROR, __file__, 1, "failed", None, exc_info
    )

    logging_setup.RedactingFilter().filter(record)

    assert record.exc_text is not None
    assert "RuntimeError: code=[REDACTED]" in record.exc_text
    assert FAKE_CODE not in record.exc_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            r"C:\Users\fake-user\AppData\Local\Temp\FairShuffle.lock",
            r"%USERPROFILE%\AppData\Local\Temp\FairShuffle.lock",
        ),
        (
            "QLockFile: C:/Users/fake-user/AppData/Local/Temp",
            "QLockFile: %USERPROFILE%/AppData/Local/Temp",
        ),
        # Windows ignores case, and a repr doubles each backslash.
        (r"c:\users\FAKE-USER\AppData", r"%USERPROFILE%\AppData"),
        (r"'C:\\Users\\fake-user\\x.lock'", r"'%USERPROFILE%\\x.lock'"),
        # Another user whose name starts the same way is not this home folder.
        (r"C:\Users\fake-user2\x.lock", r"C:\Users\fake-user2\x.lock"),
    ],
)
def test_redact_writes_the_home_folder_without_the_user_name(text: str, expected: str) -> None:
    assert redact(text, home=FAKE_HOME) == expected


def test_a_bare_root_is_never_treated_as_the_home_folder() -> None:
    assert redact("/etc/hosts", home=PurePosixPath("/")) == "/etc/hosts"


def test_the_home_folder_never_reaches_the_log_file(log_file: Path) -> None:
    logging.getLogger("fairshuffle.test").warning("Lock at %s", r"C:\Users\fake-user\Temp\x.lock")

    text = read_log(log_file)

    assert "fake-user" not in text
    assert rf"{HOME_MASK}\Temp\x.lock" in text


def test_the_filter_masks_the_real_home_folder_by_default() -> None:
    record = logging.LogRecord(
        "fairshuffle.test", logging.INFO, __file__, 1, "Home is %s", (str(Path.home()),), None
    )

    logging_setup.RedactingFilter().filter(record)

    assert record.getMessage() == f"Home is {HOME_MASK}"


def test_stop_logging_closes_the_file_and_hands_crashes_back_to_python(tmp_path: Path) -> None:
    setup_logging(tmp_path)

    stop_logging()

    assert not any(
        isinstance(h, logging_setup._FairShuffleHandler) for h in logging.getLogger().handlers
    )
    assert sys.excepthook is sys.__excepthook__


def test_a_secret_masked_before_logging_starts_is_masked_once_it_does(tmp_path: Path) -> None:
    mask_secret("fake-early-value")
    setup_logging(tmp_path)

    logging.getLogger("fairshuffle.test").info("Value fake-early-value")

    assert "fake-early-value" not in read_log(tmp_path / LOG_FILE_NAME)


def test_setting_up_again_keeps_the_values_masked_so_far(tmp_path: Path, log_file: Path) -> None:
    mask_secret("fake-kept-value")
    setup_logging(tmp_path)

    logging.getLogger("fairshuffle.test").info("Value fake-kept-value and %s", FAKE_CLIENT_ID)

    text = read_log(log_file)
    assert "fake-kept-value" not in text
    assert FAKE_CLIENT_ID not in text


def test_a_quoted_value_cut_off_before_its_closing_quote_is_still_masked() -> None:
    masked = redact(f'code="{FAKE_CODE}')

    assert masked == f'code="{MASK}'
    assert redact(masked) == masked


def test_a_long_run_of_backslashes_is_masked_quickly() -> None:
    # A path repr after a secret-looking key, cut off before its closing quote. A pattern that can
    # read the backslashes more than one way takes exponential time here and freezes the app.
    started = time.perf_counter()

    masked = redact('secret="' + "\\" * 200)

    assert time.perf_counter() - started < 1.0
    assert masked.startswith(f'secret="{MASK}')


def test_secrets_can_be_added_while_other_threads_log() -> None:
    """Worker threads learn tokens while others log; neither side may trip over the other."""
    import threading

    log_filter = RedactingFilter(["fake-secret-0"], home=PurePosixPath("/home/fake-user"))
    errors: list[BaseException] = []
    stop = threading.Event()

    def keep_logging() -> None:
        try:
            while not stop.is_set():
                record = logging.LogRecord(
                    "t", logging.INFO, __file__, 1, "x fake-secret-0", None, None
                )
                log_filter.filter(record)
        except BaseException as error:  # noqa: BLE001  # any failure fails the test below
            errors.append(error)

    workers = [threading.Thread(target=keep_logging) for _ in range(4)]
    for worker in workers:
        worker.start()
    for number in range(2000):
        log_filter.add_secret(f"fake-secret-{number}")
    stop.set()
    for worker in workers:
        worker.join()

    assert errors == []
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "fake-secret-1999", None, None)
    log_filter.filter(record)
    assert "fake-secret-1999" not in record.msg
