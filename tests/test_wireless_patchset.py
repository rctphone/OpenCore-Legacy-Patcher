"""Exercise actual macOS patch recipes and the migration guard."""

import io
import platform
import plistlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch


@unittest.skipUnless(platform.system() == "Darwin", "Requires OCLP's macOS dependencies")
class WirelessMigrationTests(unittest.TestCase):
    def setUp(self):
        from opencore_legacy_patcher.sys_patch.patchsets.hardware.networking.modern_wireless import ModernWireless
        from opencore_legacy_patcher.sys_patch.patchsets.detect import HardwarePatchsetDetection
        self.recipe = ModernWireless
        self.detection = HardwarePatchsetDetection
        self.constants = SimpleNamespace(computer=SimpleNamespace())

    def targets(self, xnu):
        recipes = self.recipe(xnu, 6, "test", self.constants).patches()
        return {name for recipe in recipes.values() for operation in recipe.values()
                for directory in operation.values() for name in directory}

    def test_sequoia_keeps_native_wifi_ui_and_daemon(self):
        self.assertEqual(self.targets(24), {
            "wifip2pd", "IO80211.framework", "WiFiPeerToPeer.framework",
        })

    def test_sonoma_keeps_its_required_extended_patches(self):
        self.assertEqual(self.targets(23), {
            "wifip2pd", "IO80211.framework", "WiFiPeerToPeer.framework",
            "airportd", "CoreWLAN.framework", "CoreWiFi.framework",
        })

    def test_supported_ventura_is_not_patched(self):
        self.assertEqual(self.targets(22), set())

    def migration_blocked(self, installed_url, patches):
        detector = self.detection.__new__(self.detection)
        detector._constants = SimpleNamespace(
            computer=SimpleNamespace(oclp_sys_url=installed_url),
            commit_info=("test", "test", "fork-commit"),
        )
        contents = io.BytesIO(plistlib.dumps(patches))
        with patch("pathlib.Path.exists", return_value=True), patch("builtins.open", return_value=contents):
            return detector._validation_check_repatching_is_possible()

    def test_old_commit_requires_unpatching(self):
        self.assertTrue(self.migration_blocked("old-upstream-commit", {"Modern Wireless": {}}))

    def test_existing_t1_requires_unpatching_even_at_same_commit(self):
        self.assertTrue(self.migration_blocked("fork-commit", {
            "Modern Wireless Common": {}, "T1 Security Chip": {},
        }))

    def test_same_commit_wireless_bootstrap_can_continue(self):
        self.assertFalse(self.migration_blocked("fork-commit", {
            "Modern Wireless Common": {}, "Commit URL": "fork-commit",
            "PatcherSupportPkg": "1.9.7",
        }))
