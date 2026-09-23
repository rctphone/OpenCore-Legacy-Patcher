"""Exercise an EFI installer against a disk-image EFI.

    python3 test_install.py <stage-dir> <diskNsM> [installer.py]

The image partition must start in the installer's BEFORE state. Only device
identity and the model/build probes are replaced; mounting, copying and
swapping run for real. The stage directory is copied, never modified.
"""
import importlib.util
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE, DEV = Path(sys.argv[1]).resolve(), sys.argv[2].removeprefix('/dev/')
SCRIPT = sys.argv[3] if len(sys.argv) > 3 else 'install.py'
STAGE = Path(tempfile.mkdtemp()) / 'stage'
shutil.copytree(SOURCE, STAGE)

spec = importlib.util.spec_from_file_location('install', STAGE / SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)
info = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', DEV]))
inst.DEVICE, inst.RAW = DEV, '/dev/r' + DEV
inst.PARTITION_UUID, inst.PARTITION_SIZE = info['DiskUUID'].upper(), info['Size']
real_output = inst.output
probes = {'hw.model': inst.MODEL, '-buildVersion': inst.BUILD}
inst.output = lambda *a: probes.get(str(a[-1])) or real_output(*a)


def efi_state():
    efi = inst.mount(read_only=True)
    try:
        return inst.state(efi), inst.inventory(efi), inst.leftovers(efi)
    finally:
        inst.unmount()


def expect_failure(label, action):
    try:
        action()
    except AssertionError as error:
        print(f'  ok, refused: {error}')
        return
    raise SystemExit(f'FAIL: {label} did not refuse')


new = inst.manifest()['new']
state0, inv0, _ = efi_state()
assert state0 == inst.BEFORE, 'test image does not start in the BEFORE state'
untouched = {k: v for k, v in inv0.items() if k not in inst.BEFORE}
print('== 1. check on the BEFORE state'); inst.check()

print('== 2. injected failure after staging, before the swap')
real_validate = inst.validate
def failing_validate(validator, config):
    if f'.{inst.TAG}-new' in str(config):
        raise AssertionError('injected validation failure')
    return real_validate(validator, config)
inst.validate = failing_validate
expect_failure('apply with injected failure', inst.apply)
inst.validate = real_validate
state, inv, left = efi_state()
assert state == inst.BEFORE and inv == inv0 and not left, 'EFI not restored after injected failure'
print('  EFI unchanged, no leftover directories')

print('== 3. apply'); inst.apply()
state, inv, left = efi_state()
assert state == new and inv == {**untouched, **new} and not left
assert all(inst.sha(inst.OLD_FILES / r) == c for r, c in inst.BEFORE.items())
assert inst.IMAGE.stat().st_size == inst.PARTITION_SIZE
print('  target files installed, other files unchanged, backups verified')

print('== 4. check and apply again are no-ops'); inst.check(); inst.apply()

print('== 5. tampered staged file is refused')
p = inst.NEW / 'OC/OpenCore.efi'; saved = p.read_bytes(); p.write_bytes(saved + b'x')
expect_failure('tampered stage', inst.check); p.write_bytes(saved)

print('== 6. rollback'); inst.rollback()
state, inv, left = efi_state()
assert state == inst.BEFORE and inv == inv0 and not left
print('  EFI back to the exact BEFORE inventory')

print('== 7. wrong macOS build is refused')
probes['-buildVersion'] = '24G830'
expect_failure('wrong build', inst.check)
shutil.rmtree(STAGE.parent)
print('ALL TESTS PASSED')
