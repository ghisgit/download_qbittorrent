from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, cast


class _LogSink:
    """Best-effort log file writer shared by stdout and stderr."""

    def __init__(self, file: TextIO) -> None:
        self._file: TextIO | None = file

    def write(self, text: str) -> None:
        file = self._file
        if file is None:
            return
        try:
            file.write(text)
        except OSError as exc:
            self._stop(file, f"写入日志失败, 已停止记录: {exc}")

    def flush(self) -> None:
        file = self._file
        if file is None:
            return
        try:
            file.flush()
        except OSError as exc:
            self._stop(file, f"刷新日志失败, 已停止记录: {exc}")

    def close(self) -> None:
        file = self._file
        self._file = None
        if file is not None:
            with suppress(OSError):
                file.close()

    def _stop(self, file: TextIO, message: str) -> None:
        self._file = None
        with suppress(OSError):
            file.close()
        # sys.stderr may itself be a _Tee; the sink is already disabled, so
        # this only reaches the console (and possibly the other stream).
        print(f"[log] 警告: {message}", file=sys.stderr)


class _Tee:
    def __init__(self, console: TextIO, sink: _LogSink) -> None:
        self._console = console
        self._sink = sink

    def write(self, text: str) -> int:
        written = self._console.write(text)
        self._sink.write(text)
        return written

    def flush(self) -> None:
        self._console.flush()
        self._sink.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._console, name)


def new_log_path(directory: str | Path, now: datetime | None = None) -> Path:
    """Return a timestamped log path, creating ``directory`` when needed."""
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)

    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    base = f"crawler_{stamp}"
    path = directory / f"{base}.log"
    suffix = 1
    while path.exists():
        path = directory / f"{base}_{suffix}.log"
        suffix += 1
    return path


@contextmanager
def capture_logs(enabled: bool, directory: str | Path) -> Iterator[Path | None]:
    """Tee stdout/stderr to a timestamped log file while it is active."""
    if not enabled:
        yield None
        return

    try:
        path = new_log_path(directory)
        file = path.open("w", encoding="utf-8", errors="replace", buffering=1)
    except OSError as exc:
        print(f"[log] 警告: 无法创建日志文件: {exc}", file=sys.stderr)
        yield None
        return

    sink = _LogSink(file)
    stdout = _Tee(sys.stdout, sink)
    stderr = _Tee(sys.stderr, sink)
    try:
        with (
            redirect_stdout(cast(TextIO, stdout)),
            redirect_stderr(cast(TextIO, stderr)),
        ):
            yield path
    finally:
        sink.close()
