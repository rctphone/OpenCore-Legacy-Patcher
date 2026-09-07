import copy
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "opencore_legacy_patcher/support/root_patch_compatibility.py"))


class RootPatchCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.constants = SimpleNamespace(computer=SimpleNamespace(real_model="MacBookPro14,2"),
            detected_os_build="24G830", detected_os=24, detected_os_minor=6,
            patcher_support_pkg_version="1.9.7", commit_info=("macbookpro14-2-sequoia", "", "new-gui-commit"))
        self.properties = {"Networking: Modern Wireless": True, "Miscellaneous: T1 Security Chip": True}
        self.recipes = {"Modern Wireless Common": {"path": "new-wifi"}, "T1 Security Chip": {"path": "same-t1"}}
        self.metadata = {"Commit URL": MODULE["DEPLOYED_COMMIT"], "PatcherSupportPkg": "v1.9.7",
            "Custom Signature": True, "OS Version": "24.6 (24G830)", **copy.deepcopy(self.recipes)}

    def current(self):
        return MODULE["target_patches_current"](self.constants, self.properties, self.metadata, self.recipes)

    def test_known_deployed_patchset_survives_gui_only_update(self):
        self.assertTrue(self.current())

    def test_changed_recipe_is_not_accepted(self):
        self.recipes["Modern Wireless Common"]["path"] = "changed"
        self.assertFalse(self.current())

    def test_old_wireless_or_unrelated_commit_is_not_accepted(self):
        self.metadata["Modern Wireless"] = {}
        self.assertFalse(self.current())
        del self.metadata["Modern Wireless"]
        self.metadata["Commit URL"] = "unknown"
        self.assertFalse(self.current())

    def test_new_os_new_payload_or_other_model_is_not_accepted(self):
        self.constants.detected_os_build = "24G999"
        self.assertFalse(self.current())
        self.constants.detected_os_build = "24G830"
        self.constants.patcher_support_pkg_version = "1.9.8"
        self.assertFalse(self.current())
        self.constants.patcher_support_pkg_version = "1.9.7"
        self.constants.computer.real_model = "MacBookPro14,1"
        self.assertFalse(self.current())
