"""Personal release profile for MacBookPro14,2; no changes to patch security."""

APPLE_NVRAM_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


def apply_quiet_profile(model: str, config: dict, *, debug_requested: bool) -> bool:
    """Disable optional diagnostics on this model unless debugging was requested.

    Keep compatibility arguments and all SIP, AMFI, FileVault and hardware
    settings intact. Lilu needs either retained symbols or DisableLinkeditJettison.
    """
    if model != "MacBookPro14,2" or debug_requested:
        return False

    optional_args = {"-v", "-v-liludbgall", "-liludbgall", "liludump=90", "debug=0x100"}
    if config["Kernel"]["Quirks"]["DisableLinkeditJettison"]:
        optional_args.add("keepsyms=1")
    nvram = config["NVRAM"]["Add"][APPLE_NVRAM_GUID]
    nvram["boot-args"] = " ".join(
        arg for arg in nvram["boot-args"].split() if arg not in optional_args
    )
    config["Misc"]["Debug"].update(
        AppleDebug=False, ApplePanic=False, DisplayLevel=0, Target=0, SysReport=False
    )
    config["#Revision"]["Fork-Profile"] = "rctphone/MacBookPro14,2-quiet-v1"
    return True
