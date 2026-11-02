"""Run one owned command and its descendants inside a Windows resource job.

No elevation, desktop interaction or machine settings. Closing the supervisor
terminates its job descendants. A STOP file requests the same owned stop path.
The output root must be new; keep credentials and raw logs private.
"""

import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import time


class BasicLimits(C.Structure):
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64),
                ("flags", W.DWORD), ("min_working_set", C.c_size_t),
                ("max_working_set", C.c_size_t), ("active_limit", W.DWORD),
                ("affinity", C.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]


class IO(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in
                ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]


class Limits(C.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IO),
                ("process_memory", C.c_size_t), ("job_memory", C.c_size_t),
                ("peak_process_memory", C.c_size_t), ("peak_job_memory", C.c_size_t)]


class Accounting(C.Structure):
    _fields_ = [("user", C.c_int64), ("kernel", C.c_int64),
                ("period_user", C.c_int64), ("period_kernel", C.c_int64),
                ("faults", W.DWORD), ("total_processes", W.DWORD),
                ("active_processes", W.DWORD), ("terminated_processes", W.DWORD)]


class Memory(C.Structure):
    _fields_ = [("cb", W.DWORD), ("faults", W.DWORD)] + [
        (name, C.c_size_t) for name in ("peak_rss", "rss", "peak_paged", "paged",
                                      "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]


def job_rss(k, job):
    # Fixed maximum is far above this finite process tree. Refuse truncation.
    class Pids(C.Structure):
        _fields_ = [("assigned", W.DWORD), ("count", W.DWORD), ("ids", C.c_size_t * 256)]
    pids = Pids()
    require(k.QueryInformationJobObject(job, 3, C.byref(pids), C.sizeof(pids), None))
    psapi = C.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, C.POINTER(Memory), W.DWORD]
    psapi.GetProcessMemoryInfo.restype = W.BOOL
    k.OpenProcess.argtypes, k.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
    k.CloseHandle.argtypes, k.CloseHandle.restype = [W.HANDLE], W.BOOL
    rss = 0
    for pid in pids.ids[:pids.count]:
        handle = k.OpenProcess(0x1000 | 0x10, False, pid)
        if handle:
            memory = Memory()
            memory.cb = C.sizeof(memory)
            if psapi.GetProcessMemoryInfo(handle, C.byref(memory), C.sizeof(memory)):
                rss += memory.rss
            k.CloseHandle(handle)
    return rss, list(pids.ids[:pids.count])


def job_api():
    k = C.WinDLL("kernel32", use_last_error=True)
    for name, args, result in (
        ("CreateJobObjectW", [C.c_void_p, W.LPCWSTR], W.HANDLE),
        ("GetCurrentProcess", [], W.HANDLE),
        ("GetProcessAffinityMask", [W.HANDLE, C.POINTER(C.c_size_t), C.POINTER(C.c_size_t)], W.BOOL),
        ("AssignProcessToJobObject", [W.HANDLE, W.HANDLE], W.BOOL),
        ("SetInformationJobObject", [W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        ("QueryInformationJobObject", [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
        ("TerminateJobObject", [W.HANDLE, W.UINT], W.BOOL),
    ):
        fn = getattr(k, name)
        fn.argtypes, fn.restype = args, result
    return k


def require(ok):
    if not ok:
        raise C.WinError(C.get_last_error())


def disk_bytes(root):
    total = 0
    for parent, dirs, files in os.walk(root):
        for name in dirs:
            if Path(parent, name).is_symlink():
                raise RuntimeError("Resource root contains a directory symlink")
        for name in files:
            try:
                total += Path(parent, name).stat().st_size
            except FileNotFoundError:
                pass
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--command-file", type=Path, required=True,
                   help="Private JSON argv/cwd. Do not put secrets in argv.")
    p.add_argument("--watch-root", type=Path, action="append", default=[],
                   help="Also count retained task-owned preparation files against disk budget")
    args = p.parse_args()
    if os.name != "nt":
        p.error("This qualified containment route requires Windows")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    candidates = set([root, *(path.resolve() for path in args.watch_root)])
    disk_roots = [path for path in candidates if not any(path != other and path.is_relative_to(other)
                                                       for other in candidates)]
    command = json.loads(args.command_file.read_text(encoding="utf-8"))
    k = job_api()
    job_name = f"Local\\shipment-capacity-{os.getpid()}-{secrets.token_hex(8)}"
    job = k.CreateJobObjectW(None, job_name)
    require(job)
    allowed, system = C.c_size_t(), C.c_size_t()
    require(k.GetProcessAffinityMask(k.GetCurrentProcess(), C.byref(allowed), C.byref(system)))
    bits = [1 << n for n in range(C.sizeof(C.c_size_t) * 8) if allowed.value & (1 << n)]
    mask = sum(bits[:2])
    limits = Limits()
    # Affinity, aggregate committed memory and kill-on-close. No breakaway.
    limits.basic.flags = 0x10 | 0x200 | 0x2000
    limits.basic.affinity = mask
    limits.job_memory = 3 * 1024 ** 3
    require(k.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
    require(k.AssignProcessToJobObject(job, k.GetCurrentProcess()))
    env = {**os.environ, "SHIPMENT_CAPACITY_RESOURCE_ROOT": str(root),
           "SHIPMENT_CAPACITY_JOB_NAME": job_name,
           "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
           "MAX_JOBS": "2", "PYTHONUTF8": "1", "PYTHONPATH": ""}
    record = {"platform": sys.platform, "supervisor_pid": os.getpid(),
              "job_name": job_name,
              "affinity_mask": mask, "logical_cores": len(bits[:2]),
              "memory_limit_bytes": limits.job_memory, "disk_limit_bytes": 2 * 1024 ** 3,
              "disk_poll_seconds": 1, "disk_enforcement": "sampled stop, not a filesystem quota",
              "disk_roots": [str(path) for path in disk_roots],
              "stop_path": str(root / "STOP"), "kill_on_supervisor_exit": True,
              "descendants_inherit_job": True, "started_epoch": time.time(), "status": "running"}
    (root / "resource-control.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    log = (root / "command.log").open("wb")
    process = subprocess.Popen(command["argv"], cwd=command["cwd"], env=env,
                               stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    peak_disk = 0
    with (root / "resources.jsonl").open("w", encoding="utf-8") as samples:
        while True:
            info, accounting = Limits(), Accounting()
            require(k.QueryInformationJobObject(job, 9, C.byref(info), C.sizeof(info), None))
            require(k.QueryInformationJobObject(job, 1, C.byref(accounting), C.sizeof(accounting), None))
            used = sum(disk_bytes(path) for path in disk_roots)
            peak_disk = max(peak_disk, used)
            rss, pids = job_rss(k, job)
            samples.write(json.dumps({"epoch": time.time(), "monotonic": time.perf_counter(),
                "job_peak_commit_bytes": info.peak_job_memory, "disk_bytes": used,
                "job_cpu_seconds": (accounting.user + accounting.kernel) / 1e7,
                "sum_process_rss_bytes": rss, "pids": pids,
                "active_processes": accounting.active_processes}) + "\n")
            samples.flush()
            reason = "stop_requested" if (root / "STOP").exists() else "disk_limit" if used > 2 * 1024 ** 3 else None
            if rss > 3 * 1024 ** 3:
                reason = "sampled_rss_limit"
            for active_path in root.glob("*/active-phase.json"):
                try:
                    active = json.loads(active_path.read_text())
                except (ValueError, FileNotFoundError):
                    continue
                if active.get("running"):
                    elapsed = time.perf_counter() - active["started_monotonic"]
                    if active["previous_seconds"] + elapsed > 2700 or elapsed > active["phase_limit_seconds"]:
                        reason = "active_trial_limit"
            if reason or process.poll() is not None:
                record.update(status=reason or "command_exited", exit_code=process.poll(),
                              finished_epoch=time.time(), peak_disk_bytes=peak_disk,
                              peak_job_commit_bytes=info.peak_job_memory,
                              active_processes_before_close=accounting.active_processes)
                (root / "resource-control.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                if reason:
                    k.TerminateJobObject(job, 80)
                # Process exit closes this noninherited handle and terminates
                # remaining owned descendants, including a forgotten server.
                return process.returncode or (80 if reason else 0)
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
