#!/usr/bin/env python3
"""Upgrade OpenCore 1.0.4 -> 1.0.8 on the reviewed MacBookPro14,2 EFI.

Replaces only the nine files in BEFORE: OpenCore.efi, its four drivers, two
tools, the BOOT bootstrap and config.plist (the reviewed config plus the
HideVerbose key OpenCore 1.0.8 requires). Kexts, ACPI and OpenCanopy
resources stay untouched. No network is used.

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
IMAGE = BACKUP / 'EFI-before-1.0.8.img'
MODEL = 'MacBookPro14,2'
BUILD = '24H23'
DEVICE = 'disk0s1'
RAW = '/dev/rdisk0s1'
PARTITION_UUID = 'E626B09B-6032-4F0C-A968-B54E008AA35A'
PARTITION_SIZE = 314572800
TAG = 'oc108'
DIRS = ('OC', 'BOOT')

# Expected on the EFI before the upgrade: OpenCore 1.0.4 from the fork payload,
# with the 2026-09-09 ATAPI hibernation build of OpenCore.efi.
BEFORE = {
    'OC/OpenCore.efi': '8aa6df29b98955c1d1b7a997b63aba8fa9176b0551708bca0aa487826aeb78f4',
    'OC/config.plist': 'c57a267a0a87db305df74703d3ff245b7533900b8ce5bc1232a7e499b777d937',
    'OC/Drivers/OpenRuntime.efi': 'a7493c410bd88f90736c0b0137d1af63694fc18168a65b2d1351ff64c40b0d65',
    'OC/Drivers/OpenCanopy.efi': 'a69b486b4c2fea2eb024df277f2b2e9d4cfe23a4399c5bfc7df14c4a77287ad8',
    'OC/Drivers/OpenLinuxBoot.efi': '5b550d4106e866ef0517f61d6eada6fc2b4569f8a9219c08ccb536e59fd365a0',
    'OC/Drivers/ResetNvramEntry.efi': '9a3264f09c7749ff7970097e0d4d63baeaf3853b7ae700a9dc637c61a088990d',
    'OC/Tools/BootKicker.efi': '68abcaba6f632353fe0d0eadc08dea08d2efe140a22633c9a1b1572462aceac5',
    'OC/Tools/OpenShell.efi': '9e7dd22f048cde05e8c1f9338b62f9539f948dcbe19f2c77be71e780cc6a718b',
    'BOOT/BOOTx64.efi': '60b14d437912e78a977c75436692ee8a7fa9e301644dbc677d648233fe2d77f3',
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
    for name in ('ocvalidate', 'ocvalidate-1.0.4'):
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
        print(f'READY: EFI matches the reviewed OpenCore 1.0.4 state. Free space {free} MB. Nothing changed.')
    elif current == new:
        print('ALREADY APPLIED: EFI carries the staged OpenCore 1.0.8 files. Nothing changed.')
    else:
        for rel in BEFORE:
            if current[rel] not in (BEFORE[rel], new[rel]):
                print('UNEXPECTED:', rel, current[rel])
        raise AssertionError('EFI is neither the reviewed 1.0.4 state nor the staged 1.0.8 state')


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
        print('ALREADY APPLIED and verified. Restart to load OpenCore 1.0.8.')
        return
    assert current == BEFORE, 'Installed files are not the reviewed 1.0.4 state'
    run('/sbin/fsck_msdos', '-n', RAW)
    backup_image()
    efi = mount(read_only=False)
    try:
        untouched = switch(efi, BEFORE, {rel: NEW / rel for rel in BEFORE}, new, STAGE / 'ocvalidate')
    finally:
        run('/bin/sync')
        unmount()
    finish(new, untouched)
    print('APPLY VERIFIED: OpenCore 1.0.8 installed. Restart required.')


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
        print('Already on the reviewed OpenCore 1.0.4 state. Nothing changed.')
        return
    assert current == manifest()['new'], 'Installed files are not the staged 1.0.8 state'
    efi = mount(read_only=False)
    try:
        untouched = switch(efi, manifest()['new'], {rel: OLD_FILES / rel for rel in BEFORE}, BEFORE,
                           STAGE / 'ocvalidate-1.0.4')
    finally:
        run('/bin/sync')
        unmount()
    finish(BEFORE, untouched)
    print('ROLLBACK VERIFIED: OpenCore 1.0.4 restored. Restart required.')


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
