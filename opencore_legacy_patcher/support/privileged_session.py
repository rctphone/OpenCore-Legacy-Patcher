"""Native administrator authentication for the installed personal fork.

The app keeps its normal user identity. A native, non-setuid child receives
commands over Authorization Services' private pipe and exits on EOF. No socket,
launch daemon, password storage, or relaxation of Dortania's helper is involved.
"""

import atexit
import base64
import ctypes
import json
import os
import select
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path


APP = Path("/Library/Application Support/Dortania/OpenCore-Patcher.app")
WORKER = APP / "Contents/MacOS/oclp-privileged-session"
_session = None
_lock = threading.RLock()


def validate_installation(app=APP):
    """Refuse elevation of user-writable or redirected installed code."""
    paths = [app, *app.parents, *app.rglob("*")]
    for path in paths:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            target = path.resolve(strict=True)
            if app not in target.parents:
                raise PermissionError(f"App symlink leaves the installed bundle: {path}")
            info = target.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError(f"Administrator-owned, non-writable installation required: {path}")
        # POSIX mode bits alone do not rule out ACL write grants.
        if os.access(path, os.W_OK):
            raise PermissionError(f"Installed path is writable by the current user: {path}")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                   check=True, capture_output=True)


class AuthorizationError(PermissionError):
    pass


class _Item(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("valueLength", ctypes.c_size_t),
                ("value", ctypes.c_void_p), ("flags", ctypes.c_uint32)]


class _Rights(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("items", ctypes.POINTER(_Item))]


class Session:
    def __init__(self):
        if Path(sys.executable).resolve() != APP / "Contents/MacOS/OpenCore-Patcher":
            raise PermissionError("Open the installed OpenCore-Patcher application from Applications before using administrator actions.")
        if not WORKER.is_file():
            raise PermissionError("The administrator component is missing. Reinstall this fork's application package.")
        validate_installation()
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        security.AuthorizationCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        security.AuthorizationCopyRights.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rights),
                                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        security.AuthorizationExecuteWithPrivileges.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_void_p)]
        security.AuthorizationFree.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        libc.fileno.argtypes = [ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        self.security, self.authorization, self.channel = security, ctypes.c_void_p(), None
        self.buffer = b""
        self._check(security.AuthorizationCreate(None, None, 0, ctypes.byref(self.authorization)))
        try:
            path = os.fsencode(WORKER)
            item = _Item(b"system.privilege.admin", 0, None, 0)
            rights = _Rights(1, ctypes.pointer(item))
            # InteractionAllowed | ExtendRights | PreAuthorize. macOS owns the prompt.
            self._check(security.AuthorizationCopyRights(self.authorization, ctypes.byref(rights),
                                                         None, 1 | 2 | 16, None))
            pipe = ctypes.c_void_p()
            argv = (ctypes.c_char_p * 1)(None)
            self._check(security.AuthorizationExecuteWithPrivileges(self.authorization, path,
                                                                    0, argv, ctypes.byref(pipe)))
            try:
                self.channel = os.fdopen(os.dup(libc.fileno(pipe)), "r+b", buffering=0)
            finally:
                libc.fclose(pipe)
            hello = self._read(20)
            if hello != {"protocol": 1, "uid": 0}:
                raise AuthorizationError("Administrator worker returned an invalid handshake")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(status):
        if status:
            if status == -60006:
                raise AuthorizationError("Administrator authentication was cancelled.")
            raise AuthorizationError(f"macOS administrator authentication failed ({status}).")

    def _read(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.channel], [], [], remaining)[0]:
                raise AuthorizationError("Administrator session stopped responding. Check the log before retrying the operation.")
            data = os.read(self.channel.fileno(), 65536)
            if not data:
                raise AuthorizationError("Administrator session ended; reopen the application to retry.")
            self.buffer += data
            if len(self.buffer) > 128 * 1024 * 1024:
                raise AuthorizationError("Administrator session returned excessive output")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def request(self, request):
        data = memoryview(json.dumps(request).encode("utf-8") + b"\n")
        while data:
            written = self.channel.write(data)
            if not written:
                raise AuthorizationError("Administrator session ended while sending the command")
            data = data[written:]
        result = self._read((request["timeout"] or 3600) + 10)
        if "error" in result:
            raise OSError(result["error"])
        return result

    def close(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.authorization:
            self.security.AuthorizationFree(self.authorization, 8)  # DestroyRights
            self.authorization = ctypes.c_void_p()


def close():
    global _session
    with _lock:
        if _session is not None:
            _session.close()
            _session = None


atexit.register(close)


def run(argv, **kwargs):
    """subprocess.run semantics for the options used by OCLP privileged calls."""
    global _session
    supported = {"stdout", "stderr", "capture_output", "text", "universal_newlines",
                 "encoding", "errors", "input", "timeout", "check", "cwd"}
    unknown = kwargs.keys() - supported
    if unknown:
        raise TypeError(f"Unsupported privileged subprocess options: {sorted(unknown)}")
    stdout, stderr = kwargs.get("stdout"), kwargs.get("stderr")
    if kwargs.get("capture_output"):
        if stdout is not None or stderr is not None:
            raise ValueError("stdout/stderr cannot be used with capture_output")
        stdout = stderr = subprocess.PIPE
    if stdout not in (None, subprocess.PIPE, subprocess.DEVNULL) or stderr not in (
            None, subprocess.PIPE, subprocess.DEVNULL, subprocess.STDOUT):
        raise ValueError("File descriptor redirection is not supported by the administrator session")
    text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") or kwargs.get("errors")
    encoding, errors = kwargs.get("encoding") or "utf-8", kwargs.get("errors") or "strict"
    input_data = kwargs.get("input") or b""
    if isinstance(input_data, str):
        input_data = input_data.encode(encoding, errors)
    request = {"argv": [os.fsdecode(arg) for arg in argv], "cwd": os.fsdecode(kwargs.get("cwd") or os.getcwd()),
               "merge_stderr": stderr == subprocess.STDOUT,
               "input": base64.b64encode(input_data).decode(), "timeout": kwargs.get("timeout") or 0}
    with _lock:
        if _session is None:
            _session = Session()
        result = _session.request(request)
    out, err = (base64.b64decode(result[key]) for key in ("stdout", "stderr"))
    if result.get("timed_out"):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=out, stderr=err)
    if text:
        out, err = (value.decode(encoding, errors).replace("\r\n", "\n").replace("\r", "\n") for value in (out, err))
    for target, value, stream in ((stdout, out, sys.stdout), (stderr, err, sys.stderr)):
        if target is None and stream is not None:
            if isinstance(value, bytes) and hasattr(stream, "buffer"):
                stream.buffer.write(value)
            else:
                stream.write(value if isinstance(value, str) else value.decode(encoding, "replace"))
            stream.flush()
    completed = subprocess.CompletedProcess(argv, result["returncode"],
        out if stdout == subprocess.PIPE else None, err if stderr == subprocess.PIPE else None)
    if kwargs.get("check"):
        completed.check_returncode()
    return completed
