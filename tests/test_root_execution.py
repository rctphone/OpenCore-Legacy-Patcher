"""An explicit sudo invocation needs no replacement setuid helper."""

import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                           "opencore_legacy_patcher/support/subprocess_wrapper.py"))


class RootExecutionTests(unittest.TestCase):
    def test_already_root_runs_command_directly(self):
        with patch("os.geteuid", return_value=0), patch("subprocess.run") as run:
            MODULE["run_as_root"](["/bin/echo", "test"], stdout=subprocess.PIPE)
            run.assert_called_once_with(["/bin/echo", "test"], stdout=subprocess.PIPE)

    def test_non_root_still_requires_dortania_helper(self):
        with patch("os.geteuid", return_value=501), patch("subprocess.run") as run:
            MODULE["run_as_root"](["/bin/echo", "test"], stdout=subprocess.PIPE)
            run.assert_called_once_with([MODULE["OCLP_PRIVILEGED_HELPER"], "/bin/echo", "test"],
                                        stdout=subprocess.PIPE)

    def test_missing_executable_never_runs(self):
        with patch("os.geteuid", return_value=0), patch("subprocess.run") as run:
            with self.assertRaises(FileNotFoundError):
                MODULE["run_as_root"](["/nonexistent/oclp-test-command"])
            run.assert_not_called()
