"""Execute argv without a shell, retaining only a bounded output prefix."""
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class ProcessCleanupError(OSError):
    """Termination could not be confirmed; cancellation must not hide this."""


@dataclass(frozen=True)
class ProcessResult:
    return_code: int
    output: str
    timed_out: bool
    cancelled: bool
    truncated: bool


def _posix_group_has_live_members(pgid: int) -> bool:
    """Inspect group membership independently of parent exit and output EOF."""
    if sys.platform.startswith("linux"):
        # killpg(pgid, 0) includes unreaped zombies, which cannot execute or
        # hold pipes. /proc exposes both the group and the execution state.
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                stat = (entry / "stat").read_text()
            except (FileNotFoundError, ProcessLookupError):
                continue  # Exited between enumeration and inspection.
            fields = stat.rsplit(") ", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in {"Z", "X"}:
                return True
        return False
    # Other POSIX systems provide execution state through ps rather than /proc.
    listing = subprocess.run(
        ["ps", "-A", "-o", "pid=,pgid=,stat="], shell=False,
        capture_output=True, text=True, check=True, timeout=1,
    )
    for line in listing.stdout.splitlines():
        pid, group, state = line.split()
        if int(group) == pgid and not state.startswith(("Z", "X")):
            return True
    return False


def _wait_for_posix_group(pgid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            live = _posix_group_has_live_members(pgid)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            raise ProcessCleanupError(f"POSIX process cleanup could not confirm termination: {exc}") from exc
        if not live:
            return
        if time.monotonic() >= deadline:
            raise ProcessCleanupError("POSIX process cleanup did not finish terminating")
        time.sleep(0.01)


class ProcessRunner:
    def __init__(self, *, env: Mapping[str, str] | None = None):
        self._env = dict(env) if env is not None else None

    def run(
        self,
        argv: Sequence[str],
        cwd: Path,
        *,
        timeout: float = 30.0,
        output_limit: int = 1048576,
        cancel: threading.Event | None = None,
    ) -> ProcessResult:
        if output_limit < 0:
            raise ValueError("output_limit must be non-negative")
        if cancel is not None and cancel.is_set():
            return ProcessResult(-1, "", False, True, False)
        captured = bytearray()
        truncated = False
        timed_out = cancelled = False
        job = process = reader = None

        def drain():
            nonlocal truncated
            while chunk := process.stdout.read(65536):
                available = max(output_limit - len(captured), 0)
                captured.extend(chunk[:available])
                truncated |= len(chunk) > available

        try:
            options = {}
            if os.name == "nt":
                from python_lab.runtime.windows import WindowsJob
                job = WindowsJob()
                options["creationflags"] = 0x00000004  # CREATE_SUSPENDED
            else:
                options["start_new_session"] = True
            process = subprocess.Popen(
                list(argv), cwd=cwd, env=self._env, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, **options,
            )
            if job is not None:
                job.assign_and_resume(process)
            reader = threading.Thread(target=drain, name="process-output", daemon=True)
            reader.start()
            deadline = time.monotonic() + timeout
            while True:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                if process.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                time.sleep(0.01)
        finally:
            # Even successful parents may leave descendants holding the output pipe.
            try:
                if job is not None:
                    try:
                        job.close()
                    except OSError as exc:
                        raise ProcessCleanupError(f"Windows process cleanup failed: {exc}") from exc
                elif process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        raise ProcessCleanupError(f"POSIX process cleanup failed: {exc}") from exc
            finally:
                if process is not None:
                    if process.poll() is None:
                        try:
                            process.kill()
                        except OSError as exc:
                            raise ProcessCleanupError(f"Process cleanup failed: {exc}") from exc
                    try:
                        process.wait(timeout=5)
                        if job is None:
                            _wait_for_posix_group(process.pid)
                    except subprocess.TimeoutExpired as exc:
                        raise ProcessCleanupError("Process cleanup did not finish terminating") from exc
                    finally:
                        if reader is not None:
                            reader.join(timeout=5)
                            if reader.is_alive():
                                # Closing a pipe held by a blocked reader can
                                # itself block. Report failure without claiming
                                # that the process tree or reader has finished.
                                raise ProcessCleanupError("Process cleanup output reader did not finish")
                        process.stdout.close()
        output = captured.decode("utf-8", errors="replace")
        # Replacement characters can expand invalid bytes; partial UTF-8 must also
        # respect the public byte limit when the returned string is re-encoded.
        encoded = output.encode("utf-8")
        if len(encoded) > output_limit:
            truncated = True
            output = encoded[:output_limit].decode("utf-8", errors="ignore")
        return ProcessResult(
            -1 if timed_out or cancelled else process.returncode,
            output, timed_out, cancelled, truncated,
        )
