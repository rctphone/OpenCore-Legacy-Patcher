"""Fault injection for EFI directory replacement, entirely in a temp folder."""
import hashlib
import json
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/install_fork.py'


class MigrationRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oclp-rollback-test-')
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        (base / 'manifest.json').write_text('{}')
        self.module = types.ModuleType('migration_test')
        self.module.__file__ = str(base / 'install_fork.py')
        exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), self.module.__dict__)
        self.module.EFI = base / 'live'
        source = base / 'EFI-build/EFI'
        files = {}
        for relative in ('OC/config.plist', 'BOOT/BOOTx64.efi'):
            live = self.module.EFI / relative
            new = source / relative
            live.parent.mkdir(parents=True, exist_ok=True)
            new.parent.mkdir(parents=True, exist_ok=True)
            live.write_bytes(b'original-' + relative.encode())
            new.write_bytes(b'new-' + relative.encode())
            files[relative] = hashlib.sha256(new.read_bytes()).hexdigest()
        self.module.MANIFEST = {'efi_files': files}
        self.module.backup_and_mount_efi = lambda: None
        self.module.run = lambda *args: None

    def assert_original(self):
        for relative in ('OC/config.plist', 'BOOT/BOOTx64.efi'):
            self.assertEqual((self.module.EFI / relative).read_bytes(), b'original-' + relative.encode())
        self.assertEqual({p.name for p in self.module.EFI.iterdir()}, {'OC', 'BOOT'})

    def test_partial_copy_leaves_live_efi_intact_and_removes_staging(self):
        original_copy = shutil.copytree
        def fail_second(source, target):
            if Path(target).name == 'BOOT.fork-new':
                Path(target).mkdir()
                raise OSError('simulated copy failure')
            return original_copy(source, target)
        with patch('shutil.copytree', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.module.install_efi()
        self.assert_original()

    def test_missing_boot_is_rejected_before_mounting(self):
        shutil.rmtree(self.module.STAGE / 'EFI-build/EFI/BOOT')
        with patch.object(self.module, 'backup_and_mount_efi') as mount:
            with self.assertRaisesRegex(AssertionError, 'Missing staged EFI directory: BOOT'):
                self.module.install_efi()
            mount.assert_not_called()
        self.assert_original()

    def test_failure_after_first_swap_restores_both_directories(self):
        original_rename = Path.rename
        def fail_boot_switch(source, target):
            if source.name == 'BOOT.fork-new':
                raise OSError('simulated rename failure')
            return original_rename(source, target)
        with patch.object(Path, 'rename', fail_boot_switch):
            with self.assertRaises(OSError):
                self.module.install_efi()
        self.assert_original()

    def test_success_installs_verified_files_and_removes_old_directories(self):
        self.module.install_efi()
        for relative in self.module.MANIFEST['efi_files']:
            self.assertEqual((self.module.EFI / relative).read_bytes(), b'new-' + relative.encode())
        self.assertEqual({p.name for p in self.module.EFI.iterdir()}, {'OC', 'BOOT'})
