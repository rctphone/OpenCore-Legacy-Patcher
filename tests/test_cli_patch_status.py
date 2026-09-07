"""CLI failures must stop the local migration script before rebooting."""

import platform
import unittest
from types import SimpleNamespace
from unittest.mock import patch


@unittest.skipUnless(platform.system() == "Darwin", "Requires OCLP's macOS dependencies")
class PatchStatusTests(unittest.TestCase):
    def test_unsuccessful_patch_and_unpatch_exit_nonzero(self):
        from opencore_legacy_patcher.support.arguments import arguments
        for name in ("_sys_patch_handler", "_sys_unpatch_handler"):
            with self.subTest(operation=name):
                handler = arguments.__new__(arguments)
                handler.constants = SimpleNamespace(custom_model=None,
                    computer=SimpleNamespace(real_model="MacBookPro14,2"),
                    payload_path="/tmp/oclp-test", root_patcher_succeeded=False)
                with patch("opencore_legacy_patcher.support.arguments.sys_patch.PatchSysVolume"):
                    with self.assertRaises(SystemExit) as result:
                        getattr(handler, name)()
                    self.assertEqual(result.exception.code, 1)

    def test_successful_patch_and_unpatch_complete(self):
        from opencore_legacy_patcher.support.arguments import arguments
        for name in ("_sys_patch_handler", "_sys_unpatch_handler"):
            with self.subTest(operation=name):
                handler = arguments.__new__(arguments)
                handler.constants = SimpleNamespace(custom_model=None,
                    computer=SimpleNamespace(real_model="MacBookPro14,2"),
                    payload_path="/tmp/oclp-test", root_patcher_succeeded=True)
                with patch("opencore_legacy_patcher.support.arguments.sys_patch.PatchSysVolume"):
                    getattr(handler, name)()
