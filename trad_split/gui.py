"""trad-split window: add memos, tick options, split.

Each item runs `python -m trad_split.cli` as its own process, so the window stays
responsive during analysis and Stop can end a run cleanly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QProcessEnvironment, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from . import cli
from .audio import AUDIO_EXTS
from .gui_options import (
    BOOLS, DESCRIPTIONS, MEMO, NUMBERS, TIPS, TUNE_FORMATS, ProgressLog, build_argv,
    initial_options, kind, save_config, session_dirs, where_hint,
)

APP_NAME = "Trad Split"
# Files dropped on the app while it is already open are passed along this socket.
SOCKET_NAME = "trad-split-gui"
# Launched from Finder or the Dock, PATH lacks Homebrew, where ffmpeg lives.
EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin"]

PATH_ROLE = Qt.UserRole


class Window(QMainWindow):
    def __init__(self, opts: dict, config: Path = cli.CONFIG_PATH):
        super().__init__()
        self.opts = opts
        self.config = config
        self.queue: list[QListWidgetItem] = []
        self.process: QProcess | None = None
        self.current: QListWidgetItem | None = None
        self.stopping = False
        self.output = ""
        self.log_state = ProgressLog()
        self.partial_shown = False
        self.finished_dirs: list[Path] = []
        self.checks: dict[str, QCheckBox] = {}

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._files_box())
        layout.addWidget(self._where_box())
        layout.addWidget(self._outputs_box())
        layout.addWidget(self._advanced_box())
        layout.addLayout(self._buttons())
        layout.addWidget(self._log_pane(), 1)
        self.setCentralWidget(body)
        self.resize(660, 900)
        self._update_buttons()

    # Layout

    def _files_box(self) -> QGroupBox:
        box = QGroupBox("Files")
        v = QVBoxLayout(box)
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setMinimumHeight(110)
        self.files.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.files)
        hint = QLabel("Drop memos, folders of memos, Reaper projects (re-cut) or session notes "
                      "(export tunes) here.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        v.addWidget(hint)
        row = QHBoxLayout()
        add = QPushButton("Add Files...")
        add.clicked.connect(self._choose_files)
        add_dir = QPushButton("Add Folder...")
        add_dir.clicked.connect(self._choose_folder)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        for w in (add, add_dir, self.remove_btn, self.clear_btn):
            row.addWidget(w)
        row.addStretch()
        v.addLayout(row)
        return box

    def _path_row(self, value, placeholder: str, title: str) -> tuple[QWidget, QLineEdit]:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(tilde(value) if value else "")
        edit.setPlaceholderText(placeholder)
        choose = QPushButton("Choose...")

        def pick():
            start = edit.text() or str(Path.home())
            folder = QFileDialog.getExistingDirectory(self, title, str(Path(start).expanduser()))
            if folder:
                edit.setText(folder)

        choose.clicked.connect(pick)
        row.addWidget(edit, 1)
        row.addWidget(choose)
        return w, edit

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: palette(placeholder-text);")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)  # never squashed
        return label

    def _where_box(self) -> QGroupBox:
        box = QGroupBox("Where things go")
        v = QVBoxLayout(box)

        self.output_check = QCheckBox("Put session folders in:")
        self.output_check.setChecked(self.opts["output"] is not None)
        row, self.output_edit = self._path_row(self.opts["output"], "Choose a folder",
                                               "Folder to put session folders in")
        line = QHBoxLayout()
        line.addWidget(self.output_check)
        line.addWidget(row, 1)
        v.addLayout(line)
        v.addWidget(self._note(
            "Each recording gets its own folder here, with an audio file for each set (and the "
            "note and Reaper project, if you make them). Untick to put it next to the recording."))

        obsidian = QCheckBox("Make an Obsidian note. My vault:")
        obsidian.setChecked(bool(self.opts["obsidian"]))
        self.checks["obsidian"] = obsidian
        row, self.vault_edit = self._path_row(self.opts["vault"], "Choose your vault folder",
                                              "Obsidian vault")
        line = QHBoxLayout()
        line.addWidget(obsidian)
        line.addWidget(row, 1)
        v.addLayout(line)
        v.addWidget(self._note(
            "A note with a player for each set, saved in the session folder. Your vault is the "
            "folder you open in Obsidian. For Obsidian to show the note, put session folders "
            "inside your vault, for example in a Sessions folder."))

        self.where_warning = QLabel()
        self.where_warning.setWordWrap(True)
        self.where_warning.setStyleSheet("color: #c0392b;")
        self.where_warning.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        v.addWidget(self.where_warning)

        for check, field in ((self.output_check, self.output_edit), (obsidian, self.vault_edit)):
            check.toggled.connect(field.parentWidget().setEnabled)
            field.parentWidget().setEnabled(check.isChecked())
            check.toggled.connect(self._update_where_warning)
            field.textChanged.connect(self._update_where_warning)
        self._update_where_warning()
        return box

    def _folders(self) -> dict:
        """The Where settings: output (None = next to each recording), vault, obsidian."""
        def path(edit: QLineEdit) -> Path | None:
            text = edit.text().strip()
            return Path(text).expanduser() if text else None
        return {"output": path(self.output_edit) if self.output_check.isChecked() else None,
                "vault": path(self.vault_edit), "obsidian": self.checks["obsidian"].isChecked()}

    def _update_where_warning(self) -> None:
        hint = where_hint(**self._folders())
        self.where_warning.setText(hint)
        self.where_warning.setVisible(bool(hint))

    def _outputs_box(self) -> QGroupBox:
        box = QGroupBox("What to make")
        grid = QGridLayout(box)
        shown = [(key, label) for key, label in BOOLS if key != "obsidian"]  # under Where
        for n, (key, label) in enumerate(shown):
            check = QCheckBox(label)
            check.setChecked(bool(self.opts[key]))
            check.setToolTip(TIPS.get(key, ""))
            self.checks[key] = check
            grid.addWidget(check, n % 4, n // 4)
        self.checks["audio"].toggled.connect(self.checks["sets_only"].setEnabled)
        self.checks["sets_only"].setEnabled(self.checks["audio"].isChecked())
        return box

    def _advanced_box(self) -> QWidget:
        outer = QWidget()
        v = QVBoxLayout(outer)
        v.setContentsMargins(0, 0, 0, 0)
        toggle = QToolButton()
        toggle.setText("Advanced")
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)
        toggle.setStyleSheet("QToolButton { border: none; }")
        v.addWidget(toggle)

        panel = QGroupBox()
        grid = QGridLayout(panel)
        self.numbers: dict[str, QDoubleSpinBox] = {}
        for n, (key, label, lo, hi, step, decimals) in enumerate(NUMBERS):
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setValue(float(self.opts[key]))
            self.numbers[key] = spin
            row, col = n % 4, 2 * (n // 4)
            grid.addWidget(QLabel(label), row, col)
            grid.addWidget(spin, row, col + 1)
        self.tune_format = QComboBox()
        self.tune_format.addItems(TUNE_FORMATS)
        self.tune_format.setCurrentText(self.opts["tune_format"])
        grid.addWidget(QLabel("Exported tune format"), 4, 0)
        grid.addWidget(self.tune_format, 4, 1)
        self.include_unnamed = QCheckBox("Export tunes still named 'Tune N'")
        grid.addWidget(self.include_unnamed, 4, 2, 1, 2)
        panel.setVisible(False)
        v.addWidget(panel)

        def show(on: bool):
            panel.setVisible(on)
            toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

        toggle.toggled.connect(show)
        self.advanced_toggle = toggle
        return outer

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        save = QPushButton("Save as Defaults")
        save.setToolTip(f"Write these settings to {self.config}")
        save.clicked.connect(self._save_defaults)
        self.open_btn = QPushButton("Open Session Folder")
        self.open_btn.clicked.connect(self._open_dirs)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.run_btn = QPushButton("Split")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._start)
        row.addWidget(save)
        row.addWidget(self.open_btn)
        row.addStretch()
        row.addWidget(self.stop_btn)
        row.addWidget(self.run_btn)
        return row

    def _log_pane(self) -> QPlainTextEdit:
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(150)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setPlaceholderText("Progress shows here.")
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return self.log

    # Files

    def add_paths(self, paths) -> None:
        present = {self.files.item(i).data(PATH_ROLE) for i in range(self.files.count())}
        for p in paths:
            p = Path(p).expanduser()
            if str(p) in present or not p.exists():
                continue
            if p.is_file() and kind(p) == MEMO and p.suffix.lower() not in AUDIO_EXTS:
                continue
            present.add(str(p))
            what = DESCRIPTIONS[kind(p)]
            item = QListWidgetItem(f"{p.name}{'/' if p.is_dir() else ''}    ({what})")
            item.setData(PATH_ROLE, str(p))
            item.setToolTip(str(p))
            self.files.addItem(item)
        self._update_buttons()

    def _choose_files(self) -> None:
        audio = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", str(Path.home()),
            f"Memos, Reaper projects, session notes ({audio} *.RPP *.rpp *.md);;"
            f"Memos ({audio});;Reaper projects (*.RPP *.rpp);;Session notes (*.md)")
        self.add_paths(paths)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder of memos", str(Path.home()))
        if folder:
            self.add_paths([folder])

    def _remove_selected(self) -> None:
        for item in self.files.selectedItems():
            if item is not self.current and item not in self.queue:
                self.files.takeItem(self.files.row(item))
        self._update_buttons()

    def _clear(self) -> None:
        for i in reversed(range(self.files.count())):
            item = self.files.item(i)
            if item is not self.current and item not in self.queue:
                self.files.takeItem(i)
        self._update_buttons()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_paths(u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile())

    # Options

    def current_options(self) -> dict:
        opts = dict(self.opts)
        for key, check in self.checks.items():
            opts[key] = check.isChecked()
        for key, spin in self.numbers.items():
            opts[key] = spin.value()
        opts.update(self._folders())
        opts["tune_format"] = self.tune_format.currentText()
        return opts

    def _save_defaults(self) -> None:
        try:
            save_config(self.config, self.current_options())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save {self.config}:\n{e}")
            return
        self._append(f"Saved defaults to {self.config}")

    # Running

    def _start(self) -> None:
        if self.process is not None:
            return
        self.queue = [self.files.item(i) for i in range(self.files.count())]
        if not self.queue:
            return
        style = self.style()
        for item in self.queue:
            item.setIcon(style.standardIcon(QStyle.SP_ArrowRight))
        self.finished_dirs = []
        self.stopping = False
        self._next()

    def _next(self) -> None:
        self._update_buttons()
        if not self.queue or self.stopping:
            for item in self.queue:
                item.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop) if self.stopping
                             else self.style().standardIcon(QStyle.SP_DialogApplyButton))
            self.queue = []
            self._update_buttons()
            return
        self.current = self.queue.pop(0)
        self.current.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        path = Path(self.current.data(PATH_ROLE))
        argv = build_argv(self.current_options(), path,
                          include_unnamed=self.include_unnamed.isChecked())
        self._append(f"\n=== {DESCRIPTIONS[kind(path)].capitalize()} {path}")

        self.output = ""
        self.log_state = ProgressLog()
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PATH", with_extra_path(env.value("PATH", "")))
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(self._finished)
        proc.errorOccurred.connect(self._error)
        self.process = proc
        self._update_buttons()
        proc.start(sys.executable, ["-m", "trad_split.cli", *argv])

    def _read(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self.output += text
        for line in self.log_state.feed(text):
            self._append(line)
        self._show_partial(self.log_state.partial)

    def _finished(self, code: int, status) -> None:
        self._read()
        if self.log_state.partial:
            self._append(self.log_state.partial)
            self.log_state.partial = ""
        ok = code == 0 and status == QProcess.NormalExit
        style = self.style()
        if ok:
            self.current.setIcon(style.standardIcon(QStyle.SP_DialogApplyButton))
            self.finished_dirs += [d for d in session_dirs(self.output) if d not in self.finished_dirs]
        elif self.stopping:
            self.current.setIcon(style.standardIcon(QStyle.SP_BrowserStop))
            self._append("Stopped.")
        else:
            self.current.setIcon(style.standardIcon(QStyle.SP_MessageBoxCritical))
            self._append(f"Failed (exit code {code}).")
        self.process.deleteLater()
        self.process = None
        self.current = None
        self._next()

    def _error(self, error) -> None:
        if error == QProcess.FailedToStart:
            self._append(f"Could not start {sys.executable}: {self.process.errorString()}")

    def _stop(self) -> None:
        if self.process is None:
            return
        self.stopping = True
        self._append("Stopping...")
        self.process.terminate()
        # Give it a moment to exit, then make sure.
        proc = self.process
        QTimer.singleShot(3000, lambda: self.process is proc and proc.kill())

    def _open_dirs(self) -> None:
        for d in self.finished_dirs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _update_buttons(self) -> None:
        busy = self.process is not None
        self.run_btn.setEnabled(not busy and self.files.count() > 0)
        self.stop_btn.setEnabled(busy)
        self.remove_btn.setEnabled(bool(self.files.selectedItems()))
        self.clear_btn.setEnabled(self.files.count() > 0)
        self.open_btn.setEnabled(bool(self.finished_dirs))
        self.open_btn.setText("Open Session Folders" if len(self.finished_dirs) > 1
                              else "Open Session Folder")

    # Log

    def _append(self, line: str) -> None:
        # Keep the progress line where it is; the next progress update starts a new one.
        self.partial_shown = False
        self.log_state.partial = ""
        self.log.appendPlainText(line)

    def _show_partial(self, text: str) -> None:
        """Show (or clear) the progress line as the last line of the log."""
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if self.partial_shown:
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.deletePreviousChar()  # the newline before it
            self.partial_shown = False
        if text:
            self.log.appendPlainText(text)
            self.partial_shown = True
        self.log.ensureCursorVisible()

    def closeEvent(self, event) -> None:
        if self.process is not None:
            answer = QMessageBox.question(self, APP_NAME, "A run is in progress. Stop it and quit?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.stopping = True
            self.process.kill()
            self.process.waitForFinished(3000)
        event.accept()


def tilde(path) -> str:
    """A path with the home folder shown as ~."""
    path, home = str(path), str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def with_extra_path(path: str) -> str:
    parts = path.split(os.pathsep) if path else []
    return os.pathsep.join([p for p in EXTRA_PATH if p not in parts] + parts)


class App(QApplication):
    """Takes files opened with the app from Finder or dropped on its Dock icon."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window: Window | None = None
        self.pending: list[str] = []

    def event(self, e) -> bool:
        if e.type() == QEvent.FileOpen:
            path = e.file()
            if self.window is not None:
                self.window.add_paths([path])
            else:
                self.pending.append(path)
            return True
        return super().event(e)


def send_to_running(paths: list[str]) -> bool:
    """Pass paths to a window that is already open. False if there is none."""
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write("\n".join(paths).encode("utf-8") + b"\n")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen(window: Window) -> QLocalServer:
    server = QLocalServer(window)
    QLocalServer.removeServer(SOCKET_NAME)  # clear a stale socket after a crash
    server.listen(SOCKET_NAME)

    def accept():
        conn = server.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def done():
            read()
            paths = [p for p in buf.decode("utf-8", "replace").splitlines() if p]
            window.add_paths(paths)
            window.raise_()
            window.activateWindow()
            conn.deleteLater()

        conn.readyRead.connect(read)
        conn.disconnected.connect(done)

    server.newConnection.connect(accept)
    return server


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    paths = [a for a in argv[1:] if not a.startswith("-")]
    app = App(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    if send_to_running(paths):
        # Seen when started from Terminal; the Dock launcher's output goes to the log.
        print(f"{APP_NAME} is already open, so " + ("the files were added to that window."
              if paths else "nothing new was opened. Close it first to start a fresh one."))
        return 0
    try:
        opts = initial_options()
    except SystemExit as e:  # a broken config file
        QMessageBox.warning(None, APP_NAME, f"{e}\n\nUsing the built-in defaults.")
        opts = initial_options(Path(os.devnull))
    window = Window(opts)
    app.window = window
    window.add_paths(paths + app.pending)
    window._server = listen(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
