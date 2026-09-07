#!/usr/bin/env python3
"""Prepare the reviewed OpenCore 1.0.4 bootstrap for the target EFI installer.

Only changes local staging files. Never writes to the mounted EFI partition.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

BOOT_SHA256 = '60b14d437912e78a977c75436692ee8a7fa9e301644dbc677d648233fe2d77f3'


def repair(stage):
    manifest_path = stage / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    root = stage / 'EFI-build/EFI'
    source = stage / 'EFI-build/System/Library/CoreServices/boot.efi'
    target = root / 'BOOT/BOOTx64.efi'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == BOOT_SHA256, 'Unexpected bootstrap binary'
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    expected = set(manifest['efi_files'])
    # Allow a retry after the file copy succeeded but the manifest write failed.
    assert actual - expected <= {'BOOT/BOOTx64.efi'} and expected <= actual, 'EFI inventory changed'
    for name, checksum in manifest['efi_files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == checksum, 'EFI checksum mismatch: ' + name
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).hexdigest() == BOOT_SHA256, 'Unexpected staged bootstrap'
    else:
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == BOOT_SHA256
    manifest['efi_files']['BOOT/BOOTx64.efi'] = BOOT_SHA256
    pending = manifest_path.with_suffix('.new')
    pending.write_text(json.dumps(manifest, indent=2) + '\n')
    pending.replace(manifest_path)
    print('BOOT staging repaired and checksummed. Run Continue-OCLP.command again.')


if __name__ == '__main__':
    repair(Path(sys.argv[1]) if len(sys.argv) == 2 else Path.home() / 'OCLP-install')
