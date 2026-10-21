"""Builds the Qt application, puts the tray icon in place and runs until the user quits."""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QDir,
    QLockFile,
    QMessageLogContext,
    QObject,
    QtMsgType,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from fairshuffle import __version__
from fairshuffle.storage.logging_setup import setup_logging
from fairshuffle.ui.account import AccountController
from fairshuffle.ui.tray import TrayIcon

APP_NAME = "FairShuffle"

log = logging.getLogger(__name__)

_QT_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def start_logging() -> None:
    """Write the log file, with Qt's own messages in it too. A logging problem never stops the app.

    The packaged app has no console, so without this Qt's warnings would go nowhere. Sending them
    through Python logging also puts them through the redaction filter: Qt quotes file paths, and
    paths under the home folder contain the Windows user name.
    """
    try:
        setup_logging(secrets=[os.environ.get("SPOTIFY_CLIENT_ID", "")])
    except OSError as error:
        # With no file handler this goes to the console, if there is one. Only the reason is
        # shown, because the full error would quote the logs folder's path.
        log.warning("Logging to a file is off: %s", error.strerror or type(error).__name__)
        return
    qInstallMessageHandler(_log_qt_message)


def _log_qt_message(mode: QtMsgType, _context: QMessageLogContext, message: str) -> None:
    logging.getLogger("fairshuffle.qt").log(
        _QT_LOG_LEVELS.get(mode, logging.WARNING), "%s", message
    )


def default_instance_key() -> str:
    """A name for this Windows user's copy of FairShuffle, so each user on a PC gets one.

    The user name is hashed only to keep it out of the lock file and socket names. That is
    tidiness, not secrecy: anyone who knows the user name can work out the same key.
    """
    try:
        user = getpass.getuser()
    except OSError:
        user = "unknown-user"
    return f"{APP_NAME}-{hashlib.sha256(user.encode()).hexdigest()[:16]}"


class SingleInstance(QObject):
    """Makes sure only one copy of FairShuffle runs for each Windows user.

    The first copy takes a lock file in the user's temp folder and listens on a local socket.
    A later copy finds the lock taken, connects to that socket to tell the first copy it was
    launched and then exits. The lock decides which copy runs; the socket only carries the
    "launched again" notice. The connection itself is the whole notice, so neither side ever
    reads or writes data on it.

    This is a convenience, not a security control: if the lock cannot be used at all, FairShuffle
    starts anyway.
    """

    activation_requested = Signal()
    QUIET_PERIOD = 5.0  # seconds; repeated launches inside it raise only one notice

    def __init__(
        self,
        key: str | None = None,
        lock_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key or default_instance_key()
        self.lock_path = (lock_dir or Path(QDir.tempPath())) / f"{self.key}.lock"
        self._lock = QLockFile(str(self.lock_path))
        # Qt treats a lock older than 30 seconds as abandoned by default, but the first copy holds
        # it for as long as it runs. With 0 a lock only counts as abandoned when the process that
        # took it is gone, for example after a crash.
        self._lock.setStaleLockTime(0)
        self._server: QLocalServer | None = None
        self._last_notice: float | None = None

    @property
    def listening(self) -> bool:
        return self._server is not None

    def acquire(self) -> bool:
        """Return True if this copy should run. The first copy then listens for later launches."""
        if self._take_lock() or self._lock_unusable():
            return True
        if self._notify_first_copy():
            return False  # the running copy logs the handover, so this copy never opens the log
        # Nobody answered. Either the first copy is still starting, or a crash left a lock file
        # behind that Qt can't read. Removing it fails while its owner is alive, so this only
        # clears an abandoned lock.
        if not self._lock.removeStaleLockFile():
            log.info("Another copy holds the lock but did not answer; exiting")
            return False
        log.info("Cleared a lock file left behind by an earlier copy")
        return self._take_lock() or self._lock_unusable()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

    def _lock_unusable(self) -> bool:
        """True if the last lock attempt failed for a reason other than another copy holding it.

        For example the temp folder is not writable. Running without the guard beats not running.
        """
        error = self._lock.error()
        if error == QLockFile.LockError.LockFailedError:
            return False
        log.warning(
            "Can't use the lock file (%s); running without the single-instance guard", error.name
        )
        return True

    def _take_lock(self) -> bool:
        if not self._lock.tryLock(0):
            return False
        self._listen()
        return True

    def _listen(self) -> None:
        server = QLocalServer(self)
        # Asks Windows to limit the named pipe to this user. That only holds if this copy creates
        # the pipe first, so nothing is ever read from it or trusted.
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self.key)  # clears a socket file left by a crash (not on Windows)
        if not server.listen(self.key):
            # This copy still runs; later launches just exit without showing a notice.
            log.warning("Can't listen for later launches: %s", server.errorString())
            return
        server.newConnection.connect(lambda: self._answer(server))
        self._server = server

    def _answer(self, server: QLocalServer) -> None:
        notify = False
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            now = time.monotonic()
            if self._last_notice is None or now - self._last_notice >= self.QUIET_PERIOD:
                self._last_notice = now
                notify = True
        if notify:
            log.info("FairShuffle was launched again; pointing the user at the tray icon")
            self.activation_requested.emit()

    def _notify_first_copy(self) -> bool:
        """Connect to the first copy and hang up. Returns True if it answered.

        Never write anything to this socket: the first copy does not read it, and staying silent
        means a program squatting on the name learns nothing.
        """
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if not socket.waitForConnected(1000):
            return False
        socket.disconnectFromServer()
        return True


def create_application() -> QApplication:
    """Return the QApplication, creating it on first use (tests share one that pytest-qt made)."""
    existing = QApplication.instance()
    # Qt's own command-line options are not used, so Qt only gets the program name.
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    # A tray app has no main window, so closing the About box must not end the app.
    app.setQuitOnLastWindowClosed(False)
    return app


def run() -> int:
    """Start FairShuffle and return its exit code once the user picks Quit."""
    start_logging()
    app = create_application()
    instance = SingleInstance()
    if not instance.acquire():
        return 0  # FairShuffle is already running; that copy shows the user where its icon is
    log.info("FairShuffle %s starting", __version__)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("The Windows notification area is not available; exiting")
        QMessageBox.critical(
            None,
            APP_NAME,
            "FairShuffle needs the Windows notification area, which is not available.",
        )
        instance.release()
        return 1
    account = AccountController()
    # In this order: the account's jobs wrap up before the lock lets a new copy start.
    app.aboutToQuit.connect(account.shutdown)
    app.aboutToQuit.connect(instance.release)
    tray = TrayIcon(quit_app=app.quit, account=account)
    instance.activation_requested.connect(tray.show_already_running)
    tray.show()
    account.start()  # resumes a saved sign-in without the browser
    exit_code = app.exec()
    log.info("FairShuffle quit with exit code %d", exit_code)
    return exit_code
