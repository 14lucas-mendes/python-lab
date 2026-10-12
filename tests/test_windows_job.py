"""Portable API seams for the Windows cleanup barrier; native CI tests the OS."""
import ctypes
from collections import deque
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from ctypes import wintypes

import pytest

import python_lab.runtime.windows as windows
from python_lab.runtime.windows import WindowsJob, _Accounting


class Kernel:
    def __init__(self, *, arrivals=0, wait_result=0, notify_arrivals=True):
        self.pids = [101, 202]
        self.total = len(self.pids)
        self.arrivals = arrivals
        self.notify_arrivals = notify_arrivals
        self.notifications = deque([(6, 101), (6, 202)])
        self.wait_result = wait_result
        self.terminated = threading.Event()
        self.exited = threading.Event()
        self.exited.set()
        self.closed = []
        self.opened = []
        self.waited = []
        self.last_error = 5
        self.open_failure = None
        self.open_error = 5
        self.queue_error = None

    def GetQueuedCompletionStatus(self, port, message, key, pid, timeout):
        if self.queue_error is not None:
            self.last_error = self.queue_error
            return False
        if not self.notifications:
            self.last_error = 258
            return False
        kind, process_id = self.notifications.popleft()
        ctypes.cast(message, ctypes.POINTER(wintypes.DWORD)).contents.value = kind
        ctypes.cast(key, ctypes.POINTER(ctypes.c_size_t)).contents.value = 1
        ctypes.cast(pid, ctypes.POINTER(ctypes.c_void_p)).contents.value = process_id
        return True

    def QueryInformationJobObject(self, handle, kind, info, size, returned):
        if kind == 1:
            accounting = ctypes.cast(info, ctypes.POINTER(_Accounting)).contents
            accounting.TotalProcesses = self.total
            accounting.ActiveProcesses = len(self.pids)
        else:
            raise AssertionError(f"Unexpected query kind: {kind}")
        return True

    def OpenProcess(self, access, inherit, pid):
        if pid == self.open_failure:
            self.last_error = self.open_error
            return 0
        handle = pid + 1000
        self.opened.append(handle)
        return handle

    def TerminateJobObject(self, handle, exit_code):
        # Job membership can disappear before these actual process objects
        # signal; a new arrival can also vanish during this same interval.
        self.total += self.arrivals
        if self.notify_arrivals:
            for index in range(self.arrivals):
                self.notifications.append((6, 303 + index))
        self.pids = []
        self.terminated.set()
        return True

    def WaitForSingleObject(self, handle, timeout):
        self.waited.append(handle)
        if not self.exited.wait(timeout / 1000):
            return 258
        return self.wait_result

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def job_for(kernel, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: kernel.last_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda error: OSError(f"Windows error {error}"), raising=False)
    job = WindowsJob.__new__(WindowsJob)
    job._kernel = kernel
    job._handle = 999
    job._port = 888
    job._process_handles = []
    job._observed_processes = 0
    return job


def test_accounting_zero_does_not_release_unsignaled_processes(monkeypatch):
    kernel = Kernel()
    kernel.exited.clear()
    job = job_for(kernel, monkeypatch)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(job.close)
        try:
            assert kernel.terminated.wait(1)
            with pytest.raises(TimeoutError):
                future.result(timeout=.05)
        finally:
            kernel.exited.set()
            future.result(timeout=1)
    assert set(kernel.waited) == {1101, 1202}
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]
    assert job._handle is None


def test_stable_lifetime_count_allows_completed_processes(monkeypatch):
    kernel = Kernel()
    job = job_for(kernel, monkeypatch)
    job.close()
    assert set(kernel.waited) == {1101, 1202}
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]


def test_unobserved_arrival_between_capture_and_termination_is_explicit_uncertainty(monkeypatch):
    kernel = Kernel(arrivals=1, notify_arrivals=False)
    ticks = iter(index * .5 for index in range(100))
    monkeypatch.setattr(windows.time, "monotonic", lambda: next(ticks))
    job = job_for(kernel, monkeypatch)
    with pytest.raises(OSError, match="observations incomplete"):
        job.close()
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]
    assert job._handle is None


@pytest.mark.parametrize("wait_result,error", [(258, "finish terminating"), (0xFFFFFFFF, "Windows error"), (7, "wait status")])
def test_process_wait_failure_is_visible_and_closes_handles(monkeypatch, wait_result, error):
    kernel = Kernel(wait_result=wait_result)
    job = job_for(kernel, monkeypatch)
    with pytest.raises(OSError, match=error):
        job.close()
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]
    assert job._handle is None


def test_capture_failure_closes_already_opened_handles(monkeypatch):
    kernel = Kernel()
    kernel.open_failure = 202
    job = job_for(kernel, monkeypatch)
    with pytest.raises(OSError, match="Windows error"):
        job.close()
    assert sorted(kernel.closed) == [888, 999, 1101]
    assert job._handle is None


def test_departed_member_notification_still_waits_actual_process(monkeypatch):
    kernel = Kernel()
    kernel.pids = []  # Both left accounting before cleanup inspected the job.
    job = job_for(kernel, monkeypatch)
    job.close()
    assert set(kernel.waited) == {1101, 1202}
    assert job._observed_processes == kernel.total
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]


def test_new_member_during_termination_is_observed_and_waited(monkeypatch):
    kernel = Kernel(arrivals=1)
    job = job_for(kernel, monkeypatch)
    job.close()
    assert set(kernel.waited) == {1101, 1202, 1303}
    assert job._observed_processes == kernel.total == 3
    assert sorted(kernel.closed) == [888, 999, 1101, 1202, 1303]


def test_already_destroyed_process_is_proven_stopped_without_a_handle(monkeypatch):
    kernel = Kernel()
    kernel.pids = []
    kernel.open_failure = 101
    kernel.open_error = 87
    job = job_for(kernel, monkeypatch)
    job.close()
    assert kernel.waited == [1202]
    assert job._observed_processes == 2
    assert sorted(kernel.closed) == [888, 999, 1202]


def test_notification_api_failure_is_visible_and_closes_job_and_port(monkeypatch):
    kernel = Kernel()
    kernel.queue_error = 6
    job = job_for(kernel, monkeypatch)
    with pytest.raises(OSError, match="Windows error 6"):
        job.close()
    assert sorted(kernel.closed) == [888, 999]
    assert job._handle is None and job._port is None


def test_handle_close_failure_still_releases_other_handles(monkeypatch):
    kernel = Kernel()
    close_handle = kernel.CloseHandle

    def close(handle):
        close_handle(handle)
        return handle != 1101

    kernel.CloseHandle = close
    job = job_for(kernel, monkeypatch)
    with pytest.raises(OSError, match="Windows error"):
        job.close()
    assert sorted(kernel.closed) == [888, 999, 1101, 1202]
    assert job._handle is None and job._port is None


@pytest.mark.parametrize("failure", [None, "limits", "port", "association"])
def test_completion_port_association_precedes_process_assignment_and_releases_on_failure(monkeypatch, failure):
    from types import SimpleNamespace
    kernel = Kernel()
    kernel.notifications.clear()
    kernel.total = 0
    kernel.pids = []
    events = []

    class Api:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def set_information(handle, kind, info, size):
        step = "limits" if kind == 9 else "association"
        events.append(step)
        if kind == 7:
            association = ctypes.cast(info, ctypes.POINTER(windows._CompletionPortInfo)).contents
            assert association.CompletionKey == 1 and association.CompletionPort == 888
        return failure != step

    def create_port(*args):
        events.append("port")
        return 0 if failure == "port" else 888

    def assign(handle, process):
        events.append("assign")
        kernel.pids.append(303)
        kernel.total += 1
        kernel.notifications.append((6, 303))
        return True

    def first_thread(snapshot, entry):
        ctypes.cast(entry, ctypes.POINTER(windows._ThreadEntry)).contents.th32OwnerProcessID = 303
        return True

    def resume(thread):
        events.append("resume")
        return 1

    functions = dict(CreateJobObjectW=lambda *args: 999, SetInformationJobObject=set_information,
                     CreateIoCompletionPort=create_port, AssignProcessToJobObject=assign,
                     CreateToolhelp32Snapshot=lambda *args: 777, Thread32First=first_thread,
                     Thread32Next=lambda *args: False, OpenThread=lambda *args: 666, ResumeThread=resume)
    for name in ("QueryInformationJobObject", "TerminateJobObject", "CloseHandle", "GetQueuedCompletionStatus",
                 "OpenProcess", "WaitForSingleObject"):
        functions[name] = getattr(kernel, name)
    for name, callback in functions.items():
        setattr(kernel, name, Api(callback))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: kernel.last_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda error: OSError(f"Windows error {error}"), raising=False)
    if failure:
        with pytest.raises(OSError, match="Windows error"):
            WindowsJob()
        assert kernel.closed == ([999, 888] if failure == "association" else [999])
    else:
        job = WindowsJob()
        job.assign_and_resume(SimpleNamespace(pid=303, _handle=55))
        assert events == ["limits", "port", "association", "assign", "resume"]
        job.close()
        assert sorted(kernel.closed) == [666, 777, 888, 999, 1303]
