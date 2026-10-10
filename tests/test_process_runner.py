import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def runner(**kwargs):
    from python_lab.runtime.processes import ProcessRunner
    return ProcessRunner(**kwargs)


def wait_for_file(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    pytest.fail(f"Child did not signal readiness: {path}")


def process_is_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # No such process
                return False
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            status = kernel.WaitForSingleObject(handle, 0)
            if status == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return status == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Containers may leave killed orphan zombies until PID 1 reaps them.
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(") ")[1].startswith("Z"))


def tree_command(tmp_path, parent_exits=False):
    child = tmp_path / "child.py"
    child.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        "if os.name != 'nt': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "os.write(1, b'x' * 2097152)\n"
        "Path('ready').write_text(str(os.getpid()))\n"
        "while not Path('release').exists(): time.sleep(.01)\n"
        "Path('leaked').write_text('descendant survived')\n"
        "time.sleep(30)\n"
    )
    parent = (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "while not Path('ready').exists(): time.sleep(.01)\n"
        + ("" if parent_exits else "time.sleep(30)\n")
    )
    return [sys.executable, "-c", parent]


def assert_tree_stopped(tmp_path):
    pid = int((tmp_path / "ready").read_text())
    (tmp_path / "release").touch()
    assert not process_is_alive(pid), f"Descendant {pid} survived cleanup"
    assert not (tmp_path / "leaked").exists()


def test_timeout_stops_descendants(tmp_path):
    process_runner = runner()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(process_runner.run, tree_command(tmp_path), tmp_path, timeout=2)
        wait_for_file(tmp_path / "ready")
        result = future.result(timeout=5)
    assert result.timed_out and not result.cancelled
    assert result.return_code != 0
    assert result.truncated
    assert len(result.output.encode()) <= 1048576
    assert_tree_stopped(tmp_path)


def test_cancel_stops_descendants(tmp_path):
    process_runner = runner()
    cancel = threading.Event()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(process_runner.run, tree_command(tmp_path), tmp_path, cancel=cancel)
        wait_for_file(tmp_path / "ready")
        cancel.set()
        result = future.result(timeout=5)
    assert result.cancelled and not result.timed_out
    assert result.return_code != 0
    assert result.truncated
    assert len(result.output.encode()) <= 1048576
    assert_tree_stopped(tmp_path)


def test_normal_exit_also_cleans_descendants_with_inherited_output(tmp_path):
    result = runner().run(tree_command(tmp_path, parent_exits=True), tmp_path, timeout=3)
    assert (tmp_path / "ready").exists()
    assert result.return_code == 0 and not result.timed_out
    assert_tree_stopped(tmp_path)


def test_output_is_bounded(tmp_path):
    result = runner().run([sys.executable, "-c", "print('x' * 2097152)"], tmp_path)
    assert result.truncated
    assert len(result.output.encode("utf-8")) <= 1048576
    assert result.return_code == 0


@pytest.mark.parametrize("data", ["b'\\xff' * 200", "('é' * 200).encode()"])
def test_output_bound_survives_invalid_and_split_utf8(tmp_path, data):
    result = runner().run([sys.executable, "-c", f"import os; os.write(1, {data})"], tmp_path, output_limit=101)
    assert result.truncated
    assert len(result.output.encode()) <= 101
    assert result.return_code == 0


def test_output_merges_stderr_and_uses_literal_argv_and_cwd(tmp_path):
    value = "hello ; $(echo nope) & spaces"
    result = runner().run([sys.executable, "-c", "import sys,os; print(sys.argv[1]); print(os.getcwd()); print('error', file=sys.stderr)", value], tmp_path)
    assert result.return_code == 0
    assert value in result.output and str(tmp_path) in result.output
    assert "error" in result.output
    assert not result.truncated


def test_pre_cancelled_run_never_starts(tmp_path):
    cancel = threading.Event()
    cancel.set()
    result = runner().run([sys.executable, "-c", "open('started', 'w').close()"], tmp_path, cancel=cancel)
    assert result.cancelled and result.return_code != 0
    assert not (tmp_path / "started").exists()


def test_runner_copies_injected_environment(tmp_path):
    env = dict(os.environ, A4_VALUE="original")
    process_runner = runner(env=env)
    env["A4_VALUE"] = "changed"
    result = process_runner.run([sys.executable, "-c", "import os; print(os.environ['A4_VALUE'])"], tmp_path)
    assert result.output.strip() == "original"


def test_missing_command_raises_oserror(tmp_path):
    with pytest.raises(FileNotFoundError):
        runner().run([str(tmp_path / "missing-program")], tmp_path)
