#!/usr/bin/env python3
"""Create a target-specific, offline, app-only Installer package.

Payload extraction uses a hidden sibling. The installed application is only
swapped after the complete new bundle is verified; failed extraction therefore
does not remove the working application. No root-patch or EFI command is run.
"""

import argparse
import hashlib
import json
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path


COMMON = r'''
import hashlib, json, os, plistlib, pwd, shutil, stat, subprocess, sys
from pathlib import Path
APP = Path('/Library/Application Support/Dortania/OpenCore-Patcher.app')
NEW = APP.with_name('.OpenCore-Patcher-gui-new.app')
PREVIOUS = APP.with_name('.OpenCore-Patcher-before-gui.app')
LINK = Path('/Applications/OpenCore-Patcher.app')
RESULT = Path('/var/tmp/oclp-gui-install-result.json')
DEPLOYED = 'b88feb4fb0f127c64202b568273ef804c26dd077'

def run(*args):
    subprocess.run(list(map(str, args)), check=True)

def output(*args):
    return subprocess.check_output(list(map(str, args))).decode().strip()

def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()

def fail(message):
    raise RuntimeError(message)

def safe_tree(path):
    if path.is_symlink() or not path.is_dir():
        fail('Unexpected directory: ' + str(path))
    for child in path.rglob('*'):
        if child.is_symlink() and path not in child.resolve().parents:
            fail('Symlink leaves its bundle/staging directory: ' + str(child))

def check_link():
    if LINK.is_symlink():
        if LINK.resolve() != APP:
            fail('Applications shortcut points to an unexpected target')
    elif LINK.exists():
        fail('Applications already contains a real application at the shortcut path')

def preflight():
    if os.geteuid() != 0 or len(sys.argv) < 4 or sys.argv[3] != '/':
        fail('Install only on the currently booted system')
    if output('/usr/sbin/sysctl', '-n', 'hw.model') != 'MacBookPro14,2':
        fail('This package is only for the reviewed MacBookPro14,2')
    if output('/usr/bin/sw_vers', '-buildVersion') != '24G830':
        fail('macOS build changed since this package was reviewed')
    home = Path(pwd.getpwnam(EXPECTED['user']).pw_dir)
    if home != Path('/Users') / EXPECTED['user'] or home.is_symlink():
        fail('Unexpected target account home directory')
    for parent in [APP.parent, *APP.parent.parents]:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            fail('Unsafe application parent: ' + str(parent))
    for line in output('/bin/ps', '-axo', 'pid=,comm=').splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[1].startswith(str(APP) + '/'):
            fail('Quit OpenCore Legacy Patcher before installing this package')
    check_link()
    return home

def verify(app):
    safe_tree(app)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('Github', {}).get('Commit URL') != EXPECTED['commit_url']:
        fail('Unexpected application source commit')
    for name, digest in EXPECTED['hashes'].items():
        if sha(app / name) != digest:
            fail('Application checksum mismatch: ' + name)
    for path in [app, *app.rglob('*')]:
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            fail('Incorrect application ownership or permissions: ' + str(path))
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
    details = subprocess.run(['/usr/bin/codesign', '-d', '--verbose=4',
        str(app / 'Contents/MacOS/oclp-privileged-session')], capture_output=True, check=True).stderr.decode()
    if 'runtime' not in details:
        fail('Administrator component is missing hardened runtime')

def cleanup(home):
    removed = []
    original = APP.with_name('OpenCore-Patcher-2.4.1-original.app')
    if original.exists() or original.is_symlink():
        safe_tree(original)
        shutil.rmtree(original)
        removed.append(str(original))
    stage = home / 'OCLP-install'
    if stage.exists() or stage.is_symlink():
        safe_tree(stage)
        state_file = stage / 'state.json'
        if state_file.is_symlink():
            fail('Unexpected migration state symlink')
        state = json.loads(state_file.read_text())
        if (state.get('phase') == 'complete-needs-reboot' and state.get('commit') == DEPLOYED
                and state.get('boot') and state['boot'] != output('/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid')):
            continuation = home / 'Desktop/Continue-OCLP.command'
            if continuation.parent.is_symlink() or continuation.is_symlink():
                fail('Unexpected continuation symlink')
            shutil.rmtree(stage)
            removed.append(str(stage))
            if continuation.is_file():
                continuation.unlink()
                removed.append(str(continuation))
    return removed
'''

PREINSTALL = r'''
try:
    preflight()
    for path in (NEW, PREVIOUS):
        if path.exists() or path.is_symlink():
            fail('An earlier application install needs review: ' + str(path))
    if APP.exists() or APP.is_symlink():
        safe_tree(APP)
except Exception as error:
    print('OCLP application installation stopped:', error, file=sys.stderr)
    sys.exit(1)
'''

POSTINSTALL = r'''
had_previous = False
installed_new = False
try:
    home = preflight()
    if PREVIOUS.exists() or PREVIOUS.is_symlink():
        fail('Unexpected previous-application backup')
    safe_tree(NEW)
    run('/usr/sbin/chown', '-R', 'root:wheel', NEW)
    run('/bin/chmod', '-RN', NEW)
    run('/bin/chmod', '-R', 'go-w', NEW)
    verify(NEW)
    if APP.exists():
        safe_tree(APP)
        APP.rename(PREVIOUS)
        had_previous = True
    NEW.rename(APP)
    installed_new = True
    verify(APP)
    check_link()
    if not LINK.is_symlink():
        LINK.symlink_to(APP)
except Exception as error:
    if installed_new:
        APP.rename(NEW)
    if had_previous:
        PREVIOUS.rename(APP)
    if NEW.is_dir() and not NEW.is_symlink():
        shutil.rmtree(NEW)
    print('OCLP application installation failed; previous app restored:', error, file=sys.stderr)
    sys.exit(1)

# Installation is already verified. Cleanup errors must not remove the valid
# new application or imply that EFI/root patching failed.
warnings = []
removed = []
try:
    if had_previous:
        shutil.rmtree(PREVIOUS)
    removed = cleanup(home)
except Exception as error:
    warnings.append(str(error))
    print('Application installed; cleanup needs review:', error, file=sys.stderr)

record = {'status': 'installed', 'commit_url': EXPECTED['commit_url'],
          'version': EXPECTED['version'], 'removed': removed, 'cleanup_warnings': warnings}
# Do not follow a preexisting temporary-file symlink when writing the result.
try:
    fd = os.open(RESULT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as target:
        json.dump(record, target, indent=2)
        target.write('\n')
except FileExistsError:
    print('Result file already exists; installation result:', json.dumps(record))
print('OCLP application installed and verified:', EXPECTED['version'])
'''


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def build(app, output, user, version):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user):
        raise ValueError('Invalid target username')
    if not re.fullmatch(r'2\.4\.1-rctphone\.[1-9][0-9]*', version):
        raise ValueError('Expected a personal fork display version')
    app = app.resolve(strict=True)
    output = output.absolute()
    if output.exists():
        raise FileExistsError(output)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    commit = info['Github']['Commit URL']
    if not re.fullmatch(r'https://github.com/rctphone/OpenCore-Legacy-Patcher/commit/[0-9a-f]{40}', commit):
        raise ValueError('Expected exact personal-fork source metadata')
    expected = {'user': user, 'version': version, 'commit_url': commit, 'hashes': {
        name: digest(app / name) for name in (
            'Contents/MacOS/OpenCore-Patcher', 'Contents/MacOS/oclp-privileged-session',
            'Contents/Resources/Universal-Binaries.dmg', 'Contents/Resources/payloads.dmg')}}
    with tempfile.TemporaryDirectory(prefix='oclp-gui-package-') as temp:
        temp = Path(temp)
        payload = temp / 'root'
        destination = payload / 'Library/Application Support/Dortania/.OpenCore-Patcher-gui-new.app'
        destination.parent.mkdir(parents=True)
        subprocess.run(['/usr/bin/ditto', '--noqtn', str(app), str(destination)], check=True)
        scripts = temp / 'scripts'
        scripts.mkdir()
        for name, body in [('preinstall', PREINSTALL), ('postinstall', POSTINSTALL)]:
            source = '#!/usr/bin/python3 -I\nEXPECTED = ' + repr(expected) + '\n' + COMMON + body
            compile(source, name, 'exec')
            script = scripts / name
            script.write_text(source)
            script.chmod(0o755)
        components = temp / 'components.plist'
        subprocess.run(['/usr/bin/pkgbuild', '--analyze', '--root', str(payload), str(components)], check=True)
        entries = plistlib.loads(components.read_bytes())
        for entry in entries:
            entry['BundleIsRelocatable'] = False
            entry['BundleIsVersionChecked'] = False
        components.write_bytes(plistlib.dumps(entries))
        subprocess.run(['/usr/bin/pkgbuild', '--root', str(payload), '--component-plist', str(components),
            '--scripts', str(scripts), '--identifier', 'io.rctphone.oclp.personal-gui',
            '--version', '2.4.1.' + version.rsplit('.', 1)[1], '--install-location', '/',
            '--ownership', 'recommended', str(output)], check=True)
    print(json.dumps({'package': str(output), **expected}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--user', default='semenovi')
    parser.add_argument('--version', default='2.4.1-rctphone.1')
    args = parser.parse_args()
    build(args.app, args.output, args.user, args.version)
