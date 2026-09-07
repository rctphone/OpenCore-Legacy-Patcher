"""Regression checks without importing the macOS GUI or touching the host EFI."""

import copy
import plistlib
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = runpy.run_path(str(ROOT / "opencore_legacy_patcher/efi_builder/quiet_profile.py"))
apply_profile = PROFILE["apply_quiet_profile"]
GUID = PROFILE["APPLE_NVRAM_GUID"]


class QuietProfileTests(unittest.TestCase):
    def setUp(self):
        self.config = plistlib.loads((ROOT / "payloads/Config/config.plist").read_bytes())
        self.config["Kernel"]["Quirks"]["DisableLinkeditJettison"] = True
        self.config["NVRAM"]["Add"][GUID]["boot-args"] = (
            "keepsyms=1 debug=0x100 -lilubetaall "
            "ipc_control_port_options=0 -nokcmismatchpanic"
        )

    def test_release_profile_retains_compatibility_arguments(self):
        self.assertTrue(apply_profile("MacBookPro14,2", self.config, debug_requested=False))
        self.assertEqual(self.config["NVRAM"]["Add"][GUID]["boot-args"],
                         "-lilubetaall ipc_control_port_options=0 -nokcmismatchpanic")
        self.assertEqual(self.config["Misc"]["Debug"]["Target"], 0)
        self.assertFalse(self.config["Misc"]["Debug"]["AppleDebug"])
        self.assertFalse(self.config["Misc"]["Debug"]["ApplePanic"])

    def test_security_filevault_and_hardware_are_unchanged(self):
        before = copy.deepcopy(self.config)
        apply_profile("MacBookPro14,2", self.config, debug_requested=False)
        self.config["NVRAM"]["Add"][GUID]["boot-args"] = before["NVRAM"]["Add"][GUID]["boot-args"]
        self.config["Misc"]["Debug"] = before["Misc"]["Debug"]
        self.config["#Revision"] = before["#Revision"]
        self.assertEqual(self.config, before)

    def test_other_models_are_unchanged(self):
        for model in ("MacBookPro14,1", "MacBookPro14,3", "MacPro5,1"):
            before = copy.deepcopy(self.config)
            self.assertFalse(apply_profile(model, self.config, debug_requested=False))
            self.assertEqual(self.config, before)

    def test_explicit_debug_request_is_respected(self):
        before = copy.deepcopy(self.config)
        self.assertFalse(apply_profile("MacBookPro14,2", self.config, debug_requested=True))
        self.assertEqual(self.config, before)

    def test_symbols_are_retained_if_linkedit_quirk_is_disabled(self):
        self.config["Kernel"]["Quirks"]["DisableLinkeditJettison"] = False
        apply_profile("MacBookPro14,2", self.config, debug_requested=False)
        self.assertIn("keepsyms=1", self.config["NVRAM"]["Add"][GUID]["boot-args"].split())

    def test_repeat_application_is_stable(self):
        apply_profile("MacBookPro14,2", self.config, debug_requested=False)
        before = copy.deepcopy(self.config)
        apply_profile("MacBookPro14,2", self.config, debug_requested=False)
        self.assertEqual(self.config, before)


if __name__ == "__main__":
    unittest.main()
