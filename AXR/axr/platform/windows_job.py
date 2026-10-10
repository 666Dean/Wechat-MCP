# SPDX-License-Identifier: AGPL-3.0-only
"""Windows broker worker limits. A Job Object is not an Agent security sandbox."""
def bind_job(process, memory=512*1024*1024):
    import win32api, win32job
    handle = win32job.CreateJobObject(None, None)
    limits = win32job.QueryInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags'] = (
        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY |
        win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
    limits['BasicLimitInformation']['ActiveProcessLimit'] = 4
    limits['ProcessMemoryLimit'] = memory
    win32job.SetInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation, limits)
    try:
        win32job.AssignProcessToJobObject(handle, process._handle)
    except Exception:
        process.kill()
        handle.Close()
        raise
    return handle
