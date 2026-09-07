# Personal MacBookPro14,2 / Sequoia branch

This branch starts at upstream **2.4.1**, with selected upstream fixes and a
quiet release profile for the 2017 13-inch MacBook Pro with four Thunderbolt
ports. It is a personal development build, not an official OCLP release.
The target system is macOS **15.7.9 (24G830)**. Hardware validation is pending.

## Changes and provenance

Cherry-picks retain their authors and original commit IDs in git history:

| Upstream commit | Reason |
| --- | --- |
| [806d47f4](https://github.com/dortania/OpenCore-Legacy-Patcher/commit/806d47f4138966ab4fe9e767705b0b1517a401c9) | Block repatching an incompatible or already patched system volume. |
| [a9795b7b](https://github.com/dortania/OpenCore-Legacy-Patcher/commit/a9795b7b5f990dc2bd2eb374edcba23e3698b7a5) | Use the smaller Modern Wireless patchset on Sequoia. |
| [aec949a1](https://github.com/dortania/OpenCore-Legacy-Patcher/commit/aec949a17c5ea52a715e013dd93d7c7d5f1f6279) | Move the pre-AVX JavaScriptCore workaround to RestrictEvents, matching newer support packages. |
| [46404c07](https://github.com/dortania/OpenCore-Legacy-Patcher/commit/46404c07ef9925bf9cb146714f1ae517780ae2a7) | Bring in the matching Lilu update. |
| [b9df76eb](https://github.com/dortania/OpenCore-Legacy-Patcher/commit/b9df76ebdf3e768b37c1cc980e8444aa837c623e) | Remove the stale import left by the JavaScriptCore change. |

PatcherSupportPkg is pinned to **1.9.7**. Its new wireless resources require the
matching patch rules above. The JavaScriptCore changes preserve compatibility
for older models without AVX; the target Kaby Lake CPU does not need that fix.

Bundled OpenCore remains **1.0.4 RELEASE**. Lilu is **1.7.1**, RestrictEvents is
the upstream-pinned **1.1.7 rolling build (b70aaa4)**, AirportBrcmFixup remains
**2.1.9**, AMFIPass remains **1.4.1**, and RSRHelper remains **1.0.2**.
Newer standalone OpenCore/Lilu/AirportBrcmFixup releases mainly add Tahoe or
other-hardware support; they are not mixed into this Sequoia backport.

The T1 recipe and native Kaby Lake graphics support are unchanged. No evidence
was found that the new wireless recipe fixes the grey Wi-Fi menu icon or the
reported EFI sleep/wake failure. Those require separate checks on the Mac.

For MacBookPro14,2, the normal build also omits the redundant standard Windows
`BlessOverride`, as required by OpenCore 1.0.4's validator. OpenCore can discover
the standard Windows loader without this entry.

## Quiet release profile

When building for MacBookPro14,2 with all three OCLP debug options disabled,
the fork disables optional OpenCore logging and removes optional diagnostic
boot arguments. It preserves Lilu/Sequoia compatibility arguments, FileVault,
AMFI/SIP requirements, hardware settings, and power settings. `keepsyms=1` is
only removed when `DisableLinkeditJettison` is enabled. Explicitly enabling
verbose, kext, or OpenCore debugging bypasses this profile.

This does not promise a performance increase: Sequoia's XNU sources mark
`debug=0x100` obsolete, and `keepsyms=1` retains diagnostic symbols rather than
enabling continuous verbose tracing.

The upstream patcher version is retained for its existing installer-resource
URLs. Identify this fork by the branch/commit URL in build metadata and by
`#Revision/Fork-Profile` in its generated OpenCore config, not by version alone.
Do not mistake an upstream 2.4.1 reinstall for this custom build.

Starting with the next distributed build, the window title, main menu, About
dialog and settings display `2.4.1-rctphone.1`. Increment `fork_revision` in
`constants.py` for each subsequent distributed personal build. The technical
upstream version stays separate for asset URLs and update comparisons; the
commit metadata still identifies the exact source. The already installed
build predates this visible label.

## Migration prerequisites and order

Prepare the complete custom app, its offline PatcherSupportPkg, and a validated
EFI generated on the target Mac **before** removing existing root patches.
Compare the resulting config with the installed one, including timeout, SIP,
AMFI/FileVault, and Wi-Fi region: upstream can inject `brcmfx-country` from a
hardware probe. Preserve the current absence of a forced country override.
Ensure local access to the Mac: Wi-Fi and SSH can disappear while root patches
are reverted.

For this target's existing `EFI/BOOT` layout, run `scripts/repair_boot_layout.py`
against the staging directory after generating its manifest and before starting
the migration. The build export stores the bootstrap under
`System/Library/CoreServices/boot.efi`; the script checks the pinned OpenCore
1.0.4 binary and copies it to `EFI/BOOT/BOOTx64.efi`, updating the manifest.
It can also repair an installation paused at `patched-efi-pending`; rerunning
the continuation then installs EFI without repeating root patches.

1. Keep one verified EFI recovery image and the existing system backup.
2. Revert the existing root patches using OCLP; restart.
3. Apply this fork's root patches to the restored system volume.
4. Install the previously reviewed and validated EFI, then restart to apply
   both the root patches and matching kext versions and quiet profile.
5. Check Wi-Fi connectivity and its menu icon, T1/Touch ID, login load, and
   lid-close sleep separately. Retain the EFI recovery copy until verified.

Do not overlay the new patchset onto the old one: on Sequoia the new recipe
keeps native `airportd`, `WiFiAgent.app`, `CoreWLAN.framework` and
`CoreWiFi.framework`. Simply applying fewer new files leaves their old
replacements behind. See [upstream PR 1179](https://github.com/dortania/OpenCore-Legacy-Patcher/pull/1179).

No EFI, NVRAM or system-volume changes are performed by checking out this branch
or running the tests. Build instructions are in [SOURCE.md](SOURCE.md). For
packaged builds, use `Build-Fork.command` instead of `Build-Project.command`
after committing changes; it supplies the actual fork commit URL to the app's
metadata. Set `OCLP_PYTHON` to the desired Python 3.11 interpreter if necessary.
An app for the Intel target needs x86_64 or universal2 Python and dependencies;
an arm64-only app built on an Apple Silicon development Mac is not suitable.

## Validation

On 2026-09-07, all **21 tests passed** under Intel Python 3.11 on the development Mac.
This includes generating an EFI in normal release mode and validating it with
OpenCore 1.0.4 (`No issues found`). Python source compilation also passed.
The x86_64 app was built from commit
`b88feb4fb0f127c64202b568273ef804c26dd077`, with PatcherSupportPkg 1.9.7
embedded for offline use. Its ad-hoc signature was verified after packaging
and again after transfer. EFI generation and validation also passed on the
actual target Mac.

The custom app is installed at the standard OCLP application path; existing
autostart entries therefore point to this fork. The first migration stage
successfully reverted the old root patches. The restart, new root patches,
EFI installation, and final hardware verification remain pending.
`scripts/Continue-OCLP.command` resumes the checked local installer after the
restart. It requires the prepared `~/OCLP-install` directory and its manifest;
it is not a standalone installer for arbitrary Macs.

## Local Intel packaging and administrative commands

`OCLP_BUILD_ARCH=x86_64` selects an Intel-only PyInstaller build; the default
remains universal2. Use Intel Python and dependencies when selecting x86_64.
The packaged app contains both its EFI resources and the offline support image.

This personal app does not have Dortania's signing identity. Administrative
CLI operations must be explicitly invoked with `sudo`; an already-root process
executes its commands directly. Non-root callers still require the original
signature-restricted helper. No debug/setuid helper with disabled signature
checks is needed. The local app receives an ad-hoc integrity signature after
packaging; it is not notarized or signed as an official Dortania release.

`--build --build-output /new/output/directory` exports the generated EFI before
temporary resources are removed. An existing destination is not overwritten.
CLI patch/unpatch operations return failure when the patcher did not report
success, so installation scripts can stop before attempting the next step.

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q opencore_legacy_patcher
```

The tests cover model isolation, explicit debug opt-in, preserved security and
hardware settings, compatibility boot arguments, and Lilu's symbol-retention
requirement. On macOS with the project dependencies installed, they also
exercise the real Ventura/Sonoma/Sequoia wireless recipes, migration guards,
and normal EFI generation followed by the matching OpenCore 1.0.4 `ocvalidate`.
The build test uses upstream example hardware in external-model mode; it is
not a substitute for generation on the actual target before installation.
Software tests do not establish sleep or Wi-Fi behaviour on the physical Mac.
