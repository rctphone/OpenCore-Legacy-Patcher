"""Check normalization against the real bundled OpenCore bootstrap layout."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_boot_layout', REPO / 'scripts/repair_boot_layout.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class BootLayoutTests(unittest.TestCase):
    def test_real_bundle_layout_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'manifest.json').write_text(json.dumps({'efi_files': {}}))
            (stage / 'EFI-build/EFI/OC').mkdir(parents=True)
            with zipfile.ZipFile(REPO / 'payloads/OpenCore/OpenCore-RELEASE.zip') as bundle:
                binary = bundle.read('OpenCore-Build/System/Library/CoreServices/boot.efi')
            source = stage / 'EFI-build/System/Library/CoreServices/boot.efi'
            source.parent.mkdir(parents=True)
            source.write_bytes(binary)
            repair.repair(stage)
            repair.repair(stage)
            self.assertEqual((stage / 'EFI-build/EFI/BOOT/BOOTx64.efi').read_bytes(), binary)
            self.assertEqual(json.loads((stage / 'manifest.json').read_text())['efi_files'],
                             {'BOOT/BOOTx64.efi': repair.BOOT_SHA256})
            source.write_bytes(b'wrong bootstrap')
            with self.assertRaisesRegex(AssertionError, 'Unexpected bootstrap binary'):
                repair.repair(stage)
