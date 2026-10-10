"""Execute argv without a shell, retaining only a bounded output prefix."""
import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    return_code: int
    output: str
    timed_out: bool
    cancelled: bool
    truncated: bool


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
                    job.close()
                elif process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    if reader is not None:
                        reader.join()
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
