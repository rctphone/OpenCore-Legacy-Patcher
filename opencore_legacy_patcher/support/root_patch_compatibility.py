"""Recognize the already deployed target patches after a GUI-only app update."""

from pathlib import Path
import plistlib

# Invalidate this compatibility pin whenever patching code/resources change.
DEPLOYED_COMMIT = "https://github.com/rctphone/OpenCore-Legacy-Patcher/commit/b88feb4fb0f127c64202b568273ef804c26dd077"
PATCH_PLIST = Path("/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist")


def target_patches_current(constants, properties, metadata=None, recipes=None):
    if constants.computer.real_model != "MacBookPro14,2" or constants.detected_os_build != "24G830":
        return False
    if constants.patcher_support_pkg_version != "1.9.7":
        return False
    enabled = {key.split(": ", 1)[-1] for key, value in properties.items()
               if value is True and not key.startswith(("Settings", "Validation"))}
    if enabled != {"Modern Wireless", "T1 Security Chip"}:
        return False
    try:
        if metadata is None:
            metadata = plistlib.loads(PATCH_PLIST.read_bytes())
        if metadata.get("Commit URL") not in {DEPLOYED_COMMIT, constants.commit_info[2]}:
            return False
        if metadata.get("PatcherSupportPkg") != "v1.9.7" or metadata.get("Custom Signature") is not True:
            return False
        expected_os = f"{constants.detected_os}.{constants.detected_os_minor} ({constants.detected_os_build})"
        if metadata.get("OS Version") != expected_os:
            return False
        if recipes is None:
            from ..sys_patch.patchsets.hardware.networking.modern_wireless import ModernWireless
            from ..sys_patch.patchsets.hardware.misc.t1_security import T1SecurityChip
            args = (constants.detected_os, constants.detected_os_minor, constants.detected_os_build, constants)
            recipes = {**ModernWireless(*args).patches(), **T1SecurityChip(*args).patches()}
        if set(recipes) != {"Modern Wireless Common", "T1 Security Chip"}:
            return False
        metadata_keys = {"OpenCore Legacy Patcher", "PatcherSupportPkg", "Time Patched", "Commit URL",
                         "Kernel Debug Kit Used", "Metal Library Used", "OS Version", "Custom Signature"}
        if set(metadata) - metadata_keys != set(recipes):
            return False
        return all(metadata.get(name) == recipe for name, recipe in recipes.items())
    except (OSError, ValueError, KeyError, plistlib.InvalidFileException):
        return False
