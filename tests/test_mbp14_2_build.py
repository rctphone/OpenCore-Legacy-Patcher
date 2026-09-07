"""Build a real release EFI in a temporary directory; never install it."""

import copy
import platform
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(platform.system() == "Darwin", "Requires OCLP's macOS dependencies")
class ModelBuildTests(unittest.TestCase):
    def test_normal_release_build_passes_opencore_validation(self):
        from opencore_legacy_patcher import constants
        from opencore_legacy_patcher.datasets import example_data
        from opencore_legacy_patcher.efi_builder.build import BuildOpenCore

        c = constants.Constants()
        c.custom_model = "MacBookPro14,2"
        # External-model mode uses model data. This is upstream's synthetic
        # Kaby Lake fixture, not a personal hardware dump.
        c.computer = copy.deepcopy(example_data.MacBookPro.MacBookPro141_SSD_Upgrade)
        c.detected_os = 24
        c.detected_os_minor = 6
        c.detected_os_build = "24G830"
        c.detected_os_version = "15.7.9"
        c.sip_status = False
        c.secure_status = False
        c.serial_settings = "None"
        c.oc_timeout = 2
        # Exercise the normal build path, including its BlessOverride handling.
        c.validate = False
        with tempfile.TemporaryDirectory(prefix="oclp-efi-test-") as directory:
            c.current_path = Path(directory)
            # The upstream console helper parses argv even during API builds.
            with patch("sys.argv", ["OpenCore-Patcher", "--build"]):
                BuildOpenCore(c.custom_model, c)
            result = subprocess.run([str(c.ocvalidate_path), str(c.plist_path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = plistlib.loads(c.plist_path.read_bytes())
            self.assertEqual(config["Misc"]["Debug"]["Target"], 0)
            self.assertEqual(config["NVRAM"]["Add"]["7C436110-AB2A-4BBB-A880-FE41995C9F82"]["boot-args"],
                             "-lilubetaall ipc_control_port_options=0 -nokcmismatchpanic")
