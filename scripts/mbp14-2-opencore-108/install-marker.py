#!/usr/bin/env python3
"""Update the OCLP version marker in the OpenCore 1.0.8 config.plist.

Only config.plist changes: NVRAM OCLP-Version 2.4.1 -> 2.5.1 (stops the
installed OCLP 2.5.1 from offering its stock OpenCore on every login) and
#Revision OpenCore-Version -> 1.0.8. The eight OpenCore binaries are
rewritten with identical content. No network is used.

    sudo /usr/bin/python3 -I ./install.py check      # read-only
    sudo /usr/bin/python3 -I ./install.py apply
    sudo /usr/bin/python3 -I ./install.py rollback
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import plistlib
from pathlib import Path

STAGE = Path(__file__).resolve().parent
NEW = STAGE / 'new/EFI'
BACKUP = STAGE / 'backup'
OLD_FILES = BACKUP / 'before/EFI'
IMAGE = BACKUP / 'EFI-before-marker.img'
MODEL = 'MacBookPro14,2'
BUILD = '24H23'
DEVICE = 'disk0s1'
RAW = '/dev/rdisk0s1'
PARTITION_UUID = 'E626B09B-6032-4F0C-A968-B54E008AA35A'
PARTITION_SIZE = 314572800
TAG = 'ocmark'
DIRS = ('OC', 'BOOT')

# Expected on the EFI before this change: the OpenCore 1.0.8 install of 2026-09-23.
BEFORE = {
    'OC/OpenCore.efi': 'bef71f879c4e12f1d84c92ed988e296de5db55101aea4e45b80f29e5efc0b072',
    'OC/config.plist': '5be6f681ca19d7940a342878618a3ba4aa84456059febf6644c0305ed7b7a80d',
    'OC/Drivers/OpenRuntime.efi': '3a0c7ac90c59f725eaef0b8c0e7d98793ee39ad4812cd9bbc58519be695d6c60',
    'OC/Drivers/OpenCanopy.efi': 'be761c611c7cb6b3ca0dd4ec9f08452880227de0ff51a8a57710c56289f21915',
    'OC/Drivers/OpenLinuxBoot.efi': '229a1a0c6e1acb7fb8f8b81417ba1d906f2cdc309958be7e5466f4c324cf2eb4',
    'OC/Drivers/ResetNvramEntry.efi': '265c49c253dc4137e698a3e38ec77248dfba2685a810bc4b12ba75730df27230',
    'OC/Tools/BootKicker.efi': 'acec7af67b70279a0ebe1828dd21844dcaabd7bbb78e7debbba7199bd58fbff8',
    'OC/Tools/OpenShell.efi': 'be239857efa987e7c17ae1260453ff2f85fa76eced058b24849a71dc8b219a99',
    'BOOT/BOOTx64.efi': '7439ddbcec43b54c0cf9d69862a1b75a21fa55e9dcdd0420e3fdc9c84176a31a'
}


def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run([str(a) for a in args], check=True)


def output(*args):
    return subprocess.check_output([str(a) for a in args]).decode().strip()


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def manifest():
    return json.loads((STAGE / 'manifest.json').read_text())


def disk_info():
    info = plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil', 'info', '-plist', DEVICE]))
    assert info.get('DiskUUID', '').upper() == PARTITION_UUID, 'Unexpected EFI partition'
    assert info['Size'] == PARTITION_SIZE, 'Unexpected EFI size'
    return info


def mount(read_only):
    assert not disk_info().get('MountPoint'), 'EFI is already mounted'
    run('/usr/sbin/diskutil', 'mount', *(['readOnly'] if read_only else []), DEVICE)
    return Path(disk_info()['MountPoint']) / 'EFI'


def unmount():
    if disk_info().get('MountPoint'):
        run('/usr/sbin/diskutil', 'unmount', DEVICE)
    assert not disk_info().get('MountPoint'), 'EFI remains mounted'


def ignored(path):
    return path.name.startswith('._') or path.name == '.DS_Store'


def inventory(efi):
    """Hashes of every file under OC and BOOT, keyed by path relative to EFI."""
    result = {}
    for name in DIRS:
        for path in (efi / name).rglob('*'):
            if path.is_file() and not ignored(path):
                result[str(path.relative_to(efi))] = sha(path)
    return result


def state(efi):
    return {rel: sha(efi / rel) if (efi / rel).is_file() else None for rel in BEFORE}


def leftovers(efi):
    return [p.name for p in efi.iterdir() if p.name.endswith(('.' + TAG + '-new', '.' + TAG + '-old'))]


def validate(validator, config):
    result = subprocess.run([str(validator), str(config)], capture_output=True, text=True)
    print(result.stdout.strip(), flush=True)
    assert result.returncode == 0 and 'No issues found' in result.stdout, 'ocvalidate reported issues'


def preflight():
    assert output('/usr/sbin/sysctl', '-n', 'hw.model') == MODEL, 'Wrong Mac model'
    assert output('/usr/bin/sw_vers', '-buildVersion') == BUILD, 'macOS changed since review'
    files = manifest()
    assert set(files['new']) == set(BEFORE), 'Staged file list differs from reviewed list'
    for rel, checksum in files['new'].items():
        assert sha(NEW / rel) == checksum, 'Staged file checksum mismatch: ' + rel
    for name in ('ocvalidate',):
        assert sha(STAGE / name) == files[name], 'Validator checksum mismatch: ' + name
    validate(STAGE / 'ocvalidate', NEW / 'OC/config.plist')
    disk_info()


def remove_tree(path):
    # FAT's AppleDouble companion can disappear when its primary file is removed.
    def onerror(function, filename, error):
        if not isinstance(error[1], FileNotFoundError):
            raise error[1]
    assert not path.is_symlink(), 'Unexpected symlink during EFI cleanup'
    shutil.rmtree(path, onerror=onerror)


def write_file(source, target):
    with open(source, 'rb') as src, open(target, 'wb') as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def switch(efi, expected, sources, targets, validator):
    """Stage complete OC and BOOT copies with the target files, then swap them in."""
    assert state(efi) == expected, 'Installed files are not in the expected state'
    assert not leftovers(efi), 'Unfinished directories from an earlier run require review'
    before = inventory(efi)
    untouched = {rel: checksum for rel, checksum in before.items() if rel not in BEFORE}
    needed = sum((efi / rel).stat().st_size for rel in before) + 8 * 1024 * 1024
    assert shutil.disk_usage(efi).free > needed, 'Not enough free space on the EFI partition'
    changed, created = [], []
    try:
        for name in DIRS:
            new = efi / (name + '.' + TAG + '-new')
            created.append(new)
            shutil.copytree(efi / name, new, copy_function=shutil.copyfile,
                            ignore=lambda d, names: [n for n in names if ignored(Path(n))])
            for rel in BEFORE:
                if rel.startswith(name + '/'):
                    write_file(sources[rel], new / rel[len(name) + 1:])
        staged = {}
        for name in DIRS:
            new = efi / (name + '.' + TAG + '-new')
            for path in new.rglob('*'):
                if path.is_file() and not ignored(path):
                    staged[name + '/' + str(path.relative_to(new))] = sha(path)
        assert staged == {**untouched, **targets}, 'Staged EFI copy does not match the plan'
        validate(validator, efi / ('OC.' + TAG + '-new') / 'config.plist')
        run('/bin/sync')
        for name in DIRS:
            live, new, old = efi / name, efi / (name + '.' + TAG + '-new'), efi / (name + '.' + TAG + '-old')
            live.rename(old)
            changed.append(name)
            new.rename(live)
        assert inventory(efi) == {**untouched, **targets}, 'Installed EFI verification failed'
    except BaseException:
        for name in reversed(changed):
            live, old = efi / name, efi / (name + '.' + TAG + '-old')
            if live.exists():
                remove_tree(live)
            old.rename(live)
        for path in created:
            if path.exists():
                remove_tree(path)
        run('/bin/sync')
        raise
    for name in DIRS:
        remove_tree(efi / (name + '.' + TAG + '-old'))
    run('/bin/sync')
    return untouched


def finish(expected, untouched):
    unmount()
    run('/sbin/fsck_msdos', '-n', RAW)
    efi = mount(read_only=True)
    try:
        assert inventory(efi) == {**untouched, **expected}, 'EFI verification after remount failed'
    finally:
        unmount()


def backup_image():
    BACKUP.mkdir(mode=0o700, exist_ok=True)
    pending = IMAGE.with_suffix('.img.new')
    with open(RAW, 'rb') as source, pending.open('wb') as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    assert pending.stat().st_size == PARTITION_SIZE, 'Incomplete EFI backup'
    checksum = sha(pending)
    assert checksum == sha(RAW), 'EFI backup verification failed'
    pending.replace(IMAGE)
    IMAGE.with_suffix('.img.sha256').write_text(checksum + '  ' + IMAGE.name + '\n')
    print('EFI image saved and verified:', IMAGE, flush=True)


def save_old_files(efi):
    for rel, checksum in BEFORE.items():
        target = OLD_FILES / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        write_file(efi / rel, target)
        assert sha(target) == checksum, 'Backup copy mismatch: ' + rel


def check():
    preflight()
    efi = mount(read_only=True)
    try:
        current = state(efi)
        assert not leftovers(efi), 'Unfinished directories from an earlier run: ' + ', '.join(leftovers(efi))
        free = shutil.disk_usage(efi).free // (1024 * 1024)
    finally:
        unmount()
    new = manifest()['new']
    if current == BEFORE:
        print(f'READY: EFI matches the OpenCore 1.0.8 install of 2026-09-23. Free space {free} MB. Nothing changed.')
    elif current == new:
        print('ALREADY APPLIED: EFI carries the updated marker. Nothing changed.')
    else:
        for rel in BEFORE:
            if current[rel] not in (BEFORE[rel], new[rel]):
                print('UNEXPECTED:', rel, current[rel])
        raise AssertionError('EFI is neither the 1.0.8 install nor the updated marker state')


def apply():
    preflight()
    new = manifest()['new']
    efi = mount(read_only=True)
    try:
        current = state(efi)
        if current == BEFORE:
            save_old_files(efi)
        untouched = {rel: c for rel, c in inventory(efi).items() if rel not in BEFORE}
    finally:
        unmount()
    if current == new:
        finish(new, untouched)
        print('ALREADY APPLIED and verified. Restart to load the updated marker.')
        return
    assert current == BEFORE, 'Installed files are not the 1.0.8 state of 2026-09-23'
    run('/sbin/fsck_msdos', '-n', RAW)
    backup_image()
    efi = mount(read_only=False)
    try:
        untouched = switch(efi, BEFORE, {rel: NEW / rel for rel in BEFORE}, new, STAGE / 'ocvalidate')
    finally:
        run('/bin/sync')
        unmount()
    finish(new, untouched)
    print('APPLY VERIFIED: OCLP version marker updated. Restart required.')


def rollback():
    preflight()
    for rel, checksum in BEFORE.items():
        assert sha(OLD_FILES / rel) == checksum, 'Missing or changed backup: ' + rel
    efi = mount(read_only=True)
    try:
        current = state(efi)
    finally:
        unmount()
    if current == BEFORE:
        print('Already on the previous 1.0.8 config. Nothing changed.')
        return
    assert current == manifest()['new'], 'Installed files are not the updated marker state'
    efi = mount(read_only=False)
    try:
        untouched = switch(efi, manifest()['new'], {rel: OLD_FILES / rel for rel in BEFORE}, BEFORE,
                           STAGE / 'ocvalidate')
    finally:
        run('/bin/sync')
        unmount()
    finish(BEFORE, untouched)
    print('ROLLBACK VERIFIED: previous 1.0.8 config restored. Restart required.')


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'check'
    assert action in ('check', 'apply', 'rollback'), 'Use check, apply or rollback'
    assert os.geteuid() == 0, 'Run with sudo in a local Terminal'
    {'check': check, 'apply': apply, 'rollback': rollback}[action]()


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('STOPPED:', repr(error), '\nDo not reboot until this error is reviewed.', file=sys.stderr, flush=True)
        raise
