"""Exercise the actual native wire protocol without requesting root privileges."""

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("session_under_test", ROOT / "opencore_legacy_patcher/support/privileged_session.py")
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


@unittest.skipUnless(sys.platform == "darwin", "macOS native worker")
class NativeProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = (ROOT / "ci_tooling/privileged_session/main.m").read_text()
        # Compile a test-only copy with just the root/path entry guard removed.
        # Production source offers no debug flag or bypass mode.
        source = source.replace("geteuid() != 0 || !trustedExecutable() || ", "")
        source = source.replace(" || setuid(0) != 0", "")
        path = Path(cls.temp.name) / "protocol.m"
        path.write_text(source)
        cls.binary = Path(cls.temp.name) / "protocol-test"
        subprocess.run(["/usr/bin/xcrun", "clang", "-fobjc-arc", "-framework", "Foundation",
                        str(path), "-o", str(cls.binary)], check=True, capture_output=True)
        cls.production = Path(cls.temp.name) / "production-worker"
        subprocess.run(["/usr/bin/xcrun", "clang", "-fobjc-arc", "-framework", "Foundation",
                        str(ROOT / "ci_tooling/privileged_session/main.m"), "-o", str(cls.production)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.process = subprocess.Popen([self.binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        hello = json.loads(self.process.stdout.readline())
        self.assertEqual(hello, {"protocol": 1, "uid": os.geteuid()})

    def tearDown(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.process.stdout.close()

    def command(self, argv, **options):
        request = {"argv": argv, "input": "", "merge_stderr": False, "timeout": 10, **options}
        self.process.stdin.write(json.dumps(request).encode() + b"\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        for stream in ("stdout", "stderr"):
            if stream in response:
                response[stream] = base64.b64decode(response[stream])
        return response

    def test_exit_code_and_streams_then_session_reuse(self):
        result = self.command(["/bin/sh", "-c", "echo output; echo problem >&2; exit 7"])
        self.assertEqual((result["returncode"], result["stdout"], result["stderr"]), (7, b"output\n", b"problem\n"))
        self.assertEqual(self.command(["/usr/bin/id", "-u"])["stdout"], f"{os.geteuid()}\n".encode())

    def test_input_large_output_and_no_shell_interpolation(self):
        data = b"input\x00bytes" * 50000
        result = self.command(["/bin/cat"], input=base64.b64encode(data).decode())
        self.assertEqual(result["stdout"], data)
        result = self.command(["/bin/echo", "$(touch /nonexistent/file); `id`"])
        self.assertEqual(result["stdout"], b"$(touch /nonexistent/file); `id`\n")

    def test_timeout_and_merge(self):
        result = self.command(["/bin/sleep", "5"], timeout=0.05)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["returncode"], -9)
        result = self.command(["/bin/sh", "-c", "echo error >&2"], merge_stderr=True)
        self.assertEqual(result["stdout"], b"error\n")
        self.assertEqual(result["stderr"], b"")

    def test_descendant_stdout_cannot_stall_session(self):
        result = self.command(["/bin/sh", "-c", "sleep 4 & echo done"])
        self.assertEqual(result["stdout"], b"done\n")
        self.assertEqual(self.command(["/bin/echo", "reused"])["returncode"], 0)

    def test_environment_sanitized_and_relative_commands_rejected(self):
        result = self.command(["/usr/bin/env"])
        self.assertIn(b"HOME=/var/root\n", result["stdout"])
        self.assertNotIn(b"PYTHON", result["stdout"])
        self.assertIn("error", self.command(["id", "-u"]))

    def test_production_worker_rejects_unprivileged_or_uninstalled_launch(self):
        result = subprocess.run([self.production], input=b"{}\n", capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 77)
        self.assertEqual(result.stdout, b"")


class SessionGuardTests(unittest.TestCase):
    def test_user_owned_installation_rejected_before_codesign(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(subprocess, "run") as run:
            with self.assertRaises(PermissionError):
                session.validate_installation(Path(folder))
            run.assert_not_called()

    def test_unsupported_redirection_rejected_before_authentication(self):
        with patch.object(session, "Session") as authenticate:
            with self.assertRaises(ValueError):
                session.run(["/usr/bin/id"], stdout=123)
            with self.assertRaises(TypeError):
                session.run(["/usr/bin/id"], shell=True)
            authenticate.assert_not_called()

    def test_result_text_check_and_timeout_semantics(self):
        result = {"returncode": 3, "stdout": base64.b64encode(b"out\r\n").decode(), "stderr": "", "timed_out": False}
        with patch.object(session, "_session") as worker:
            worker.request.return_value = result
            completed = session.run([Path("/usr/bin/id")], capture_output=True, text=True)
            self.assertEqual(completed.stdout, "out\n")
            with self.assertRaises(subprocess.CalledProcessError):
                session.run(["/usr/bin/id"], capture_output=True, check=True)
            result["timed_out"] = True
            with self.assertRaises(subprocess.TimeoutExpired):
                session.run(["/usr/bin/id"], timeout=1)

    def test_denied_or_cancelled_authentication_is_explicit(self):
        for status in (-60006, -60007):
            with self.assertRaises(session.AuthorizationError):
                session.Session._check(status)

    def test_transport_has_bounded_handshake(self):
        read_fd, write_fd = os.pipe()
        channel = os.fdopen(read_fd, "rb", buffering=0)
        worker = session.Session.__new__(session.Session)
        worker.channel, worker.buffer = channel, b""
        try:
            with self.assertRaises(session.AuthorizationError):
                worker._read(0.02)
        finally:
            channel.close()
            os.close(write_fd)
