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


def tree_command(tmp_path, parent_exits=False, closed_output=False):
    child = tmp_path / "child.py"
    child.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        "if os.name != 'nt': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        + ("" if closed_output else "os.write(1, b'x' * 2097152)\n")
        + "Path('ready').write_text(str(os.getpid()))\n"
        "while not Path('release').exists(): time.sleep(.01)\n"
        "Path('leaked').write_text('descendant survived')\n"
        "time.sleep(30)\n"
    )
    parent = (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        + ("subprocess.Popen([sys.executable, 'child.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
           if closed_output else "subprocess.Popen([sys.executable, 'child.py'])\n")
        + "while not Path('ready').exists(): time.sleep(.01)\n"
        + ("" if parent_exits else "time.sleep(30)\n")
    )
    return [sys.executable, "-c", parent]


def assert_tree_stopped(tmp_path, diagnostics=None):
    pid = int((tmp_path / "ready").read_text())
    (tmp_path / "release").touch()
    assert not process_is_alive(pid), f"Descendant {pid} survived cleanup; diagnostics={diagnostics}"
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


def observe_windows_job_cleanup(monkeypatch):
    """On failure, distinguish membership accounting from process signaling."""
    import ctypes
    from ctypes import wintypes
    from python_lab.runtime.windows import WindowsJob, _Accounting

    class PidList(ctypes.Structure):
        _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                    ("pids", ctypes.c_size_t * 256)]

    records = []
    original_close = WindowsJob.close

    def close(job):
        kernel = job._kernel
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        query = kernel.QueryInformationJobObject
        terminate = kernel.TerminateJobObject
        handles = {}

        def snapshot(stage):
            members = PidList()
            record = {"stage": stage}
            if query(job._handle, 3, ctypes.byref(members), ctypes.sizeof(members), None):
                pids = list(members.pids[:members.listed])
                record.update(assigned=members.assigned, listed=members.listed, pids=pids)
                for pid in pids:
                    if pid not in handles:
                        handle = kernel.OpenProcess(0x00100000, False, pid)
                        if handle:
                            handles[pid] = handle
                        else:
                            record.setdefault("open_errors", {})[pid] = ctypes.get_last_error()
            else:
                record["query_error"] = ctypes.get_last_error()
            record["process_waits"] = {
                pid: kernel.WaitForSingleObject(handle, 0) for pid, handle in handles.items()
            }
            records.append(record)

        def terminate_job(*args):
            snapshot("before_terminate")
            result = terminate(*args)
            error = ctypes.get_last_error()
            snapshot("after_terminate")
            ctypes.set_last_error(error)
            return result

        def query_job(handle, kind, info, size, returned):
            result = query(handle, kind, info, size, returned)
            error = ctypes.get_last_error()
            if result and kind == 1:
                active = ctypes.cast(info, ctypes.POINTER(_Accounting)).contents.ActiveProcesses
                if active == 0:
                    snapshot("accounting_zero")
            ctypes.set_last_error(error)
            return result

        kernel.TerminateJobObject = terminate_job
        kernel.QueryInformationJobObject = query_job
        try:
            original_close(job)
        finally:
            kernel.TerminateJobObject = terminate
            kernel.QueryInformationJobObject = query
            records.append({"stage": "after_close", "process_waits": {
                pid: kernel.WaitForSingleObject(handle, 0) for pid, handle in handles.items()
            }})
            for handle in handles.values():
                kernel.CloseHandle(handle)

    monkeypatch.setattr(WindowsJob, "close", close)
    return records


@pytest.mark.parametrize("outcome", ["normal", "timeout", "cancel"])
def test_closed_output_descendant_is_stopped_before_return(tmp_path, outcome, monkeypatch):
    diagnostics = observe_windows_job_cleanup(monkeypatch) if os.name == "nt" else None
    cancel = threading.Event()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(
            runner().run, tree_command(tmp_path, parent_exits=outcome == "normal", closed_output=True),
            tmp_path, timeout=1 if outcome == "timeout" else 5, cancel=cancel,
        )
        wait_for_file(tmp_path / "ready")
        if outcome == "cancel":
            cancel.set()
        result = future.result(timeout=5)
    assert result.timed_out == (outcome == "timeout")
    assert result.cancelled == (outcome == "cancel")
    assert_tree_stopped(tmp_path, diagnostics)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal delivery synchronization seam")
def test_closed_output_cleanup_waits_for_delayed_signal_delivery(tmp_path, monkeypatch):
    import python_lab.runtime.processes as processes
    delivered = threading.Event()
    actual_killpg = os.killpg
    group = []

    def delay_signal(pgid, sig):
        group.append((pgid, sig))
        delivered.set()

    monkeypatch.setattr(processes.os, "killpg", delay_signal)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(runner().run, tree_command(tmp_path, parent_exits=True, closed_output=True), tmp_path)
        try:
            wait_for_file(tmp_path / "ready")
            assert delivered.wait(5), "Cleanup never requested termination"
            # Parent and its output reader are done; only the closed-output child
            # remains. Signal delivery is held until we observe the wait.
            from concurrent.futures import TimeoutError
            with pytest.raises(TimeoutError):
                future.result(timeout=.2)
            assert process_is_alive(int((tmp_path / "ready").read_text()))
        finally:
            for pgid, sig in group:
                try:
                    actual_killpg(pgid, sig)
                except ProcessLookupError:
                    pass
            future.result(timeout=5)
    assert_tree_stopped(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group confirmation")
def test_posix_cleanup_reports_confirmation_timeout(monkeypatch):
    import python_lab.runtime.processes as processes
    monkeypatch.setattr(processes, "_posix_group_has_live_members", lambda pgid: True, raising=False)
    with pytest.raises(OSError, match="cleanup.*terminat"):
        processes._wait_for_posix_group(123, timeout=.02)


@pytest.mark.skipif(os.name == "nt", reason="POSIX group inspection failure")
def test_posix_cleanup_reports_unavailable_group_inspection(monkeypatch):
    import python_lab.runtime.processes as processes

    def unavailable(pgid):
        raise PermissionError("process state unavailable")

    monkeypatch.setattr(processes, "_posix_group_has_live_members", unavailable)
    with pytest.raises(OSError, match="cleanup could not confirm termination"):
        processes._wait_for_posix_group(123)


@pytest.mark.skipif(os.name == "nt", reason="POSIX cleanup error propagation")
def test_runner_never_returns_success_when_group_cleanup_cannot_be_confirmed(tmp_path, monkeypatch):
    import python_lab.runtime.processes as processes

    def unavailable(pgid, **kwargs):
        raise OSError("controlled cleanup confirmation failure")

    monkeypatch.setattr(processes, "_wait_for_posix_group", unavailable)
    with pytest.raises(OSError, match="cleanup confirmation failure"):
        runner().run([sys.executable, "-c", "pass"], tmp_path)


def native_zombie_leader_command(tmp_path):
    import shutil
    import subprocess
    compiler = shutil.which("cc")
    assert compiler, "Native pthread regression requires a C compiler"
    source = tmp_path / "threaded_child.c"
    source.write_text(r'''
#include <pthread.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>

static void *worker(void *unused) {
    FILE *ready = fopen("ready", "w");
    if (!ready) _exit(2);
    fprintf(ready, "%d %ld", getpid(), syscall(SYS_gettid));
    fclose(ready);
    while (access("release", F_OK) != 0) usleep(10000);
    FILE *leak = fopen("leaked", "w");
    if (leak) fclose(leak);
    for (;;) usleep(10000);
    return NULL;
}

int main(void) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, worker, NULL) != 0) return 3;
    pthread_exit(NULL);
}
''')
    executable = tmp_path / "threaded_child"
    subprocess.run([compiler, "-pthread", str(source), "-o", str(executable)], check=True, capture_output=True)
    parent = (
        "import subprocess, time\nfrom pathlib import Path\n"
        f"child = subprocess.Popen([{str(executable)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "while not Path('ready').exists(): time.sleep(.01)\n"
        "while Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ', 1)[1].split()[0] != 'Z': time.sleep(.01)\n"
        "Path('leader_exited').touch()\n"
        "while not Path('parent_release').exists(): time.sleep(.01)\n"
    )
    return [sys.executable, "-c", parent]


def linux_task_state(path):
    try:
        return path.read_text().rsplit(") ", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux zombie leader and live pthread regression")
def test_zombie_leader_with_live_worker_delays_cleanup_completion(tmp_path, monkeypatch):
    import python_lab.runtime.processes as processes
    from concurrent.futures import TimeoutError
    actual_killpg = os.killpg
    requested = threading.Event()
    group = []

    def delay_signal(pgid, sig):
        group.append((pgid, sig))
        requested.set()

    monkeypatch.setattr(processes.os, "killpg", delay_signal)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(runner().run, native_zombie_leader_command(tmp_path), tmp_path)
        try:
            wait_for_file(tmp_path / "leader_exited")
            pid, tid = map(int, (tmp_path / "ready").read_text().split())
            leader = Path(f"/proc/{pid}/stat")
            task = Path(f"/proc/{pid}/task/{tid}/stat")
            assert linux_task_state(leader) == "Z"
            assert linux_task_state(task) not in {None, "Z", "X"}
            (tmp_path / "parent_release").touch()
            assert requested.wait(5), "Cleanup never requested termination"
            with pytest.raises(TimeoutError):
                future.result(timeout=.2)
            assert linux_task_state(task) not in {None, "Z", "X"}
        finally:
            for pgid, sig in group:
                try:
                    actual_killpg(pgid, sig)
                except ProcessLookupError:
                    pass
            if not group:
                (tmp_path / "parent_release").touch()
                # Permit the cleanup request after a failed readiness assertion.
                if requested.wait(5):
                    for pgid, sig in group:
                        actual_killpg(pgid, sig)
            future.result(timeout=5)
    assert linux_task_state(task) in {None, "Z", "X"}
    (tmp_path / "release").touch()
    assert not (tmp_path / "leaked").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux genuine zombie confirmation")
def test_genuine_zombie_with_no_live_tasks_is_stopped(tmp_path):
    import subprocess
    import python_lab.runtime.processes as processes
    child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        stat = Path(f"/proc/{child.pid}/stat")
        while linux_task_state(stat) != "Z" and time.monotonic() < deadline:
            time.sleep(.01)
        assert linux_task_state(stat) == "Z", "Child did not become a genuine zombie"
        assert {linux_task_state(task / "stat") for task in Path(f"/proc/{child.pid}/task").iterdir()} == {"Z"}
        processes._wait_for_posix_group(child.pid, timeout=.05)
    finally:
        child.wait(timeout=5)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux complete task inspection")
@pytest.mark.parametrize("uncertainty", ["missing_directory", "empty_directory", "missing_stat", "unreadable_stat"])
def test_zombie_leader_incomplete_task_inspection_is_cleanup_error(tmp_path, monkeypatch, uncertainty):
    import python_lab.runtime.processes as processes
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text("1234 (zombie leader) Z 1 999 0")
    tasks = proc / "task"
    if uncertainty != "missing_directory":
        tasks.mkdir()
    if uncertainty in {"missing_stat", "unreadable_stat"}:
        task = tasks / "1235"
        task.mkdir()
        if uncertainty == "unreadable_stat":
            (task / "stat").write_text("1235 (worker) S 1 999 0")
            original_read = Path.read_text

            def read(path, *args, **kwargs):
                if path == task / "stat":
                    raise PermissionError("task state unavailable")
                return original_read(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(processes, "Path", lambda value: tmp_path if value == "/proc" else Path(value))
    with pytest.raises(processes.ProcessCleanupError, match="could not confirm termination"):
        processes._wait_for_posix_group(999, timeout=.02)
