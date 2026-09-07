#!/usr/bin/env python3
"""Local two-boot migration for the reviewed MacBookPro14,2 only.

The staging directory contains this script, manifest.json, OpenCore-Patcher.app,
EFI-build/EFI, and ocvalidate. No network is used by this installer.
"""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

STAGE = Path(__file__).resolve().parent
MANIFEST = json.loads((STAGE / 'manifest.json').read_text())
STATE_FILE = STAGE / 'state.json'
APP = Path('/Library/Application Support/Dortania/OpenCore-Patcher.app')
ORIGINAL_APP = APP.with_name('OpenCore-Patcher-2.4.1-original.app')
EFI = Path('/Volumes/EFI/EFI')
RECOVERY = STAGE.parent / 'EFI-recovery-2026-09-07'
DEVICE = 'disk0s1'
PARTITION_UUID = 'E626B09B-6032-4F0C-A968-B54E008AA35A'
PARTITION_SIZE = 314572800


def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run([str(a) for a in args], check=True, cwd=STAGE)


def output(*args):
    return subprocess.check_output([str(a) for a in args]).decode().strip()


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def plist(path):
    return plistlib.loads(Path(path).read_bytes())


def state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(phase):
    record = {'phase': phase, 'boot': output('/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'),
              'commit': MANIFEST['commit']}
    temp = STATE_FILE.with_suffix('.new')
    temp.write_text(json.dumps(record, indent=2) + '\n')
    temp.replace(STATE_FILE)


def disk_info():
    info = plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil', 'info', '-plist', DEVICE]))
    assert info.get('DiskUUID', '').upper() == PARTITION_UUID, 'Unexpected EFI partition'
    assert info['Size'] == PARTITION_SIZE, 'Unexpected EFI size'
    assert info.get('MountPoint', '') in ('', '/Volumes/EFI'), 'Unexpected EFI mount point'
    return info


def check_app(app):
    info = plist(app / 'Contents/Info.plist')
    assert info['Github']['Commit URL'] == MANIFEST['commit_url'], 'Wrong app build'
    assert sha(app / 'Contents/MacOS/OpenCore-Patcher') == MANIFEST['app_executable_sha256'], 'App checksum mismatch'
    assert sha(app / 'Contents/Resources/Universal-Binaries.dmg') == MANIFEST['psp_sha256'], 'Offline patches checksum mismatch'
    assert sha(app / 'Contents/Resources/payloads.dmg') == MANIFEST['payloads_sha256'], 'EFI resources checksum mismatch'
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)


def check_assets():
    assert output('/usr/sbin/sysctl', '-n', 'hw.model') == 'MacBookPro14,2', 'Wrong Mac model'
    assert output('/usr/bin/sw_vers', '-buildVersion') == '24G830', 'macOS changed since review'
    assert MANIFEST['commit_url'] == 'https://github.com/rctphone/OpenCore-Legacy-Patcher/commit/' + MANIFEST['commit']
    check_app(STAGE / 'OpenCore-Patcher.app')
    assert sha(STAGE / 'ocvalidate') == MANIFEST['ocvalidate_sha256'], 'Validator checksum mismatch'
    root = STAGE / 'EFI-build/EFI'
    assert (root / 'BOOT/BOOTx64.efi').is_file(), 'Missing staged bootstrap; run repair_boot_layout.py before installation'
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    assert actual == set(MANIFEST['efi_files']), 'EFI file inventory changed'
    for name, checksum in MANIFEST['efi_files'].items():
        assert sha(root / name) == checksum, 'EFI checksum mismatch: ' + name
    run(STAGE / 'ocvalidate', root / 'OC/config.plist')


def backup_and_mount_efi():
    info = disk_info()
    if info.get('MountPoint'):
        run('/usr/sbin/diskutil', 'unmount', DEVICE)
    assert not disk_info().get('MountPoint'), 'EFI remains mounted'
    assert RECOVERY.is_dir() and not RECOVERY.is_symlink(), 'Expected recovery directory missing'
    new_image = RECOVERY / 'EFI-before.img.new'
    with open('/dev/rdisk0s1', 'rb') as source, new_image.open('wb') as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    assert new_image.stat().st_size == PARTITION_SIZE, 'Incomplete EFI backup'
    checksum = sha(new_image)
    assert checksum == sha('/dev/rdisk0s1'), 'EFI backup verification failed'
    run('/sbin/fsck_msdos', '-p', '/dev/rdisk0s1')
    run('/sbin/fsck_msdos', '-n', '/dev/rdisk0s1')
    run('/usr/sbin/diskutil', 'mount', 'readOnly', DEVICE)
    assert sha(EFI / 'OC/config.plist') == MANIFEST['previous_config_sha256'], 'Installed EFI changed since review'
    new_image.replace(RECOVERY / 'EFI-before.img')
    (RECOVERY / 'EFI-before.img.sha256').write_text(checksum + '  EFI-before.img\n')
    owner = STAGE.parent.stat()
    for p in (RECOVERY / 'EFI-before.img', RECOVERY / 'EFI-before.img.sha256'):
        os.chown(p, owner.st_uid, owner.st_gid)
    print('One current EFI recovery image retained and verified.', flush=True)
    shutil.copy2(EFI / 'OC/config.plist', RECOVERY / 'config-before-fork.plist')
    (RECOVERY / 'README.txt').write_text('EFI image refreshed and SHA256-verified immediately before fork migration.\nconfig-before-fork.plist matches this image. The older config-before.plist is historical.\n')


def install_app():
    if ORIGINAL_APP.exists():
        check_app(APP)  # Resume only if the expected fork is already installed.
        return
    assert APP.is_dir(), 'Official app missing'
    pending = APP.with_name('.OpenCore-Patcher-fork-new.app')
    assert not pending.exists(), 'Unfinished app copy requires review'
    run('/usr/bin/ditto', STAGE / 'OpenCore-Patcher.app', pending)
    run('/usr/sbin/chown', '-R', 'root:wheel', pending)
    run('/bin/chmod', '-R', 'go-w', pending)
    check_app(pending)
    APP.rename(ORIGINAL_APP)
    try:
        pending.rename(APP)
        check_app(APP)
    except BaseException:
        if APP.exists():
            APP.rename(pending)
        ORIGINAL_APP.rename(APP)
        raise


def install_efi():
    # Validate the complete layout before mounting or changing the live EFI.
    for name in ('OC', 'BOOT'):
        assert (STAGE / 'EFI-build/EFI' / name).is_dir(), 'Missing staged EFI directory: ' + name
    backup_and_mount_efi()
    run('/usr/sbin/diskutil', 'unmount', DEVICE)
    run('/usr/sbin/diskutil', 'mount', DEVICE)
    changed = []
    created = []
    try:
        # Stage and verify both folders before switching either live directory.
        for name in ('OC', 'BOOT'):
            live, new, old = EFI / name, EFI / (name + '.fork-new'), EFI / (name + '.fork-old')
            assert live.is_dir() and not new.exists() and not old.exists(), 'Unexpected EFI directory state'
            created.append(name)
            shutil.copytree(STAGE / 'EFI-build/EFI' / name, new)
            for rel, checksum in MANIFEST['efi_files'].items():
                if rel.startswith(name + '/'):
                    assert sha(new / rel[len(name) + 1:]) == checksum, 'EFI copy failed'
        run('/bin/sync')
        for name in ('OC', 'BOOT'):
            live, new, old = EFI / name, EFI / (name + '.fork-new'), EFI / (name + '.fork-old')
            live.rename(old)
            changed.append(name)
            new.rename(live)
        run(STAGE / 'ocvalidate', EFI / 'OC/config.plist')
        for rel, checksum in MANIFEST['efi_files'].items():
            assert sha(EFI / rel) == checksum, 'Installed EFI verification failed'
    except BaseException:
        for name in reversed(changed):
            live, old = EFI / name, EFI / (name + '.fork-old')
            if live.exists():
                shutil.rmtree(live)
            old.rename(live)
        for name in created:
            pending = EFI / (name + '.fork-new')
            if pending.exists():
                shutil.rmtree(pending)
        run('/bin/sync')
        raise
    for name in changed:
        shutil.rmtree(EFI / (name + '.fork-old'))
    run('/bin/sync')
    run('/usr/sbin/diskutil', 'unmount', DEVICE)
    run('/sbin/fsck_msdos', '-n', '/dev/rdisk0s1')
    run('/usr/sbin/diskutil', 'mount', 'readOnly', DEVICE)
    assert sha(EFI / 'OC/config.plist') == MANIFEST['efi_files']['OC/config.plist']


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else 'check'
    assert action in ('check', 'prepare', 'patch'), 'Use check, prepare or patch'
    check_assets()
    if action == 'check':
        print('Read-only checks passed. Nothing installed.')
        return
    assert os.geteuid() == 0, 'Run prepare/patch with sudo on the Mac'
    current = state()
    assert not current or current['commit'] == MANIFEST['commit'], 'Migration state belongs to another build'
    if action == 'prepare':
        assert current.get('phase') in (None, 'app-installed'), 'Prepare already completed; follow the recorded migration stage'
        backup_and_mount_efi()
        install_app()
        save_state('app-installed')
        run(APP / 'Contents/MacOS/OpenCore-Patcher', '--unpatch_sys_vol')
        save_state('unpatched')
        print('STAGE 1 SUCCESS: fork app installed; old root patches reverted. Save work and restart. Then open Continue-OCLP.command on the Desktop.')
        return
    assert current.get('phase') in ('unpatched', 'patched-efi-pending'), 'Prepare stage must complete first'
    if current['phase'] == 'unpatched':
        assert current['boot'] != output('/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'), 'Restart after reverting root patches first'
        assert not Path('/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist').exists(), 'Old root patches still present; do not overlay new patches'
        check_app(APP)
        run(APP / 'Contents/MacOS/OpenCore-Patcher', '--patch_sys_vol')
        save_state('patched-efi-pending')
    install_efi()
    save_state('complete-needs-reboot')
    print('STAGE 2 SUCCESS: new root patches and matching EFI installed. Save work and restart; then SSH verification can resume.')


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('STOPPED:', repr(error), '\nDo not advance or reboot until this error is reviewed.', file=sys.stderr, flush=True)
        raise
