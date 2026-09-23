# OpenCore 1.0.8 on the MacBookPro14,2 target

Two guarded, offline EFI installers used on 2026-09-23 on the 2017 13-inch
MacBook Pro (T1, macOS Sequoia 15.8 `24H23`) that boots through OpenCore
Legacy Patcher. They follow the approach of `scripts/install_fork.py` on the
`macbookpro14-2-sequoia` branch, but touch far less of the EFI.

## What changed on the EFI

Before: OpenCore 1.0.4 from the fork payload, with the 2026-09-09 build of
`OpenCore.efi` carrying the first version of the ATAPI hibernation fix
(`REL-104-2026-09-09`).

`install.py` replaces exactly nine files with the OpenCore 1.0.8 RELEASE build
of acidanthera/OpenCorePkg master `2cc2362`, which contains the merged fix from
[acidanthera/OpenCorePkg#626](https://github.com/acidanthera/OpenCorePkg/pull/626):

- `OC/OpenCore.efi`, `BOOT/BOOTx64.efi`
- `OC/Drivers/{OpenRuntime,OpenCanopy,OpenLinuxBoot,ResetNvramEntry}.efi`
- `OC/Tools/{BootKicker,OpenShell}.efi`
- `OC/config.plist`: the reviewed config plus `HideVerbose = false` on its four
  driver entries, the only key OpenCore 1.0.8's `ocvalidate` required

Kexts, ACPI and OpenCanopy resources are untouched. The binaries are the ones in
`payloads/OpenCore/OpenCore-RELEASE.zip` on `main`; `manifest.json` pins their
hashes. `BEFORE` in the script pins every replaced file, cross-checked against
the fork payload and the 2026-09-09 installation manifest.

`install-marker.py` then changes only `config.plist`: NVRAM `OCLP-Version`
2.4.1 → 2.5.1 and `#Revision/OpenCore-Version` → 1.0.8. The installed stock
OCLP 2.5.1 compares that marker with its own version at every login
(`sys_patch/auto_patcher/start.py`) and otherwise offers to rebuild the EFI
with its stock OpenCore 1.0.6, which lacks the hibernation fix. The marker is
not used for anything else. Decline that offer whenever it reappears.

Target configs are not committed: they carry the OCLP hardware probe.

## Using the installers

Each stage directory on the target holds the script, its manifest,
`new/EFI/...` and `ocvalidate` (plus the 1.0.4 validator for the first stage's
rollback). Run from a local Terminal:

```sh
sudo /usr/bin/python3 -I ./install.py check      # read-only: READY / ALREADY APPLIED
sudo /usr/bin/python3 -I ./install.py apply
sudo /usr/bin/python3 -I ./install.py rollback
```

`apply` pins model, macOS build, EFI partition UUID and size, staged hashes and
the installed state, validates the new config, saves a raw image of the whole
partition and the replaced files under `backup/`, stages complete `OC` and
`BOOT` copies beside the live ones, swaps them only after verification, then
runs `fsck_msdos -n` and re-verifies from a read-only remount. Any failure puts
the original directories back. `ROLLBACK*.txt` covers recovery without macOS.

## Validation

- `test_install.py` runs the real mount, copy and swap code against a GPT/FAT32
  disk image, replacing only device identity and the model/build probes:
  check, injected failure after staging (EFI unchanged, no leftovers), apply,
  repeated check/apply, tampered stage, rollback to the exact original
  inventory, wrong macOS build. All passed for both installers.
- On the target: `check` → READY, `apply` → verified, reboot →
  `opencore-version = REL-108-2026-09-22`; the marker stage → NVRAM
  `OCLP-Version = 2.5.1`.
- Hibernation with `hibernatemode 25`: `Entering Sleep state`, `Wake from
  Standby`, `HibernateStats … rd=287 ms`, `IOHibernateState = 2`, same boot
  session UUID. The 2026-09-09 build measured `rd=286 ms`.

Run hibernation tests from the Mac's own Terminal. With `ttyskeepawake 1`, an
open remote SSH session makes `powerd` hold a `ttyassertion`, and
`pmset sleepnow` then enters DarkWake instead of sleep, so the test proves
nothing.
