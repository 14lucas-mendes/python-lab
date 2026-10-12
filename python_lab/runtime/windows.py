"""Windows Job Objects contain descendants before any user code executes.

Popen closes the primary thread handle, so resume its suspended thread via the
Tool Help API after assigning the process to the job. No taskkill/PID-tree race.
"""
import ctypes
import math
import time
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _CompletionPortInfo(ctypes.Structure):
    _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", wintypes.HANDLE)]


class WindowsJob:
    def __init__(self):
        self._kernel = kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = self._port = None
        self._process_handles = []
        self._observed_processes = 0
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "CreateIoCompletionPort": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.c_size_t, wintypes.DWORD], wintypes.HANDLE),
            "GetQueuedCompletionStatus": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        }
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes = args
            function.restype = result
        try:
            self._handle = kernel.CreateJobObjectW(None, None)
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._port = kernel.CreateIoCompletionPort(ctypes.c_void_p(-1).value, None, 0, 1)
            if not self._port:
                raise ctypes.WinError(ctypes.get_last_error())
            association = _CompletionPortInfo(1, self._port)
            # Associate before assignment/resume so even fast departed children
            # leave creation records; an active PID snapshot cannot cover them.
            if not kernel.SetInformationJobObject(self._handle, 7, ctypes.byref(association), ctypes.sizeof(association)):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self._release()
            raise

    def assign_and_resume(self, process):
        kernel = self._kernel
        if not kernel.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process.pid:
                    thread = kernel.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        kernel.CloseHandle(thread)
                    return
                found = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Suspended process has no primary thread")
        finally:
            kernel.CloseHandle(snapshot)

    def _release(self):
        error = None
        handles = [handle for pid, handle in self._process_handles]
        handles.extend(handle for handle in (self._handle, self._port) if handle)
        self._process_handles = []
        self._handle = self._port = None
        for handle in handles:
            if not self._kernel.CloseHandle(handle) and error is None:
                error = ctypes.WinError(ctypes.get_last_error())
        if error is not None:
            raise error

    def _drain_notifications(self, deadline, *, timeout_ms=0):
        while True:
            if time.monotonic() >= deadline:
                raise OSError("Windows process membership observations incomplete before cleanup deadline")
            message = wintypes.DWORD()
            key = ctypes.c_size_t()
            pid = ctypes.c_void_p()
            if not self._kernel.GetQueuedCompletionStatus(
                self._port, ctypes.byref(message), ctypes.byref(key), ctypes.byref(pid), timeout_ms
            ):
                error = ctypes.get_last_error()
                if error == 258 and pid.value is None:  # WAIT_TIMEOUT, no packet
                    return
                raise ctypes.WinError(error)
            timeout_ms = 0
            if key.value != 1:
                raise OSError("Windows process membership notification has an unexpected key")
            if message.value == 6:  # JOB_OBJECT_MSG_NEW_PROCESS
                if not pid.value:
                    raise OSError("Windows process membership notification is missing a PID")
                handle = self._kernel.OpenProcess(0x00100000, False, pid.value)  # SYNCHRONIZE
                if handle:
                    self._process_handles.append((pid.value, handle))
                elif ctypes.get_last_error() != 87:  # Object already destroyed
                    raise ctypes.WinError(ctypes.get_last_error())
                self._observed_processes += 1
            # EXIT_PROCESS/accounting-zero notifications do not prove that the
            # process object has signaled; keep its handle until the real wait.

    def _accounting(self):
        accounting = _Accounting()
        if not self._kernel.QueryInformationJobObject(
            self._handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return accounting

    def close(self):
        if not self._handle:
            return
        deadline = time.monotonic() + 5
        waited = 0
        try:
            self._drain_notifications(deadline)
            if not self._kernel.TerminateJobObject(self._handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            while True:
                self._drain_notifications(deadline)
                accounting = self._accounting()
                if accounting.TotalProcesses < self._observed_processes:
                    raise OSError("Windows process membership observations exceed lifetime accounting")
                if accounting.ActiveProcesses == 0 and accounting.TotalProcesses == self._observed_processes:
                    while waited < len(self._process_handles):
                        pid, handle = self._process_handles[waited]
                        remaining = max(0, math.ceil((deadline - time.monotonic()) * 1000))
                        status = self._kernel.WaitForSingleObject(handle, remaining)
                        if status == 258:
                            raise OSError(f"Windows process {pid} did not finish terminating")
                        if status == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        if status != 0:
                            raise OSError(f"Windows process {pid} returned unexpected wait status {status}")
                        waited += 1
                    # Include creations racing the initial drain/termination or
                    # process waits. Missing NEW_PROCESS packets cannot silently
                    # pass: lifetime accounting must match observed creations.
                    self._drain_notifications(deadline)
                    accounting = self._accounting()
                    if (accounting.ActiveProcesses == 0 and
                            accounting.TotalProcesses == self._observed_processes and
                            waited == len(self._process_handles)):
                        return
                self._drain_notifications(deadline, timeout_ms=10)
        finally:
            self._release()
