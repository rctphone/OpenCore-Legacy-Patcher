#!/usr/bin/env python3
"""Preserve the reviewed Wi-Fi country setting in a target-generated EFI."""
import argparse
import hashlib
import plistlib
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("baseline", type=Path)
parser.add_argument("candidate", type=Path)
args = parser.parse_args()
baseline_bytes = args.baseline.read_bytes()
assert hashlib.sha256(baseline_bytes).hexdigest() == "dc76adfec8237ca3cf62f64fb5b740bf73607d09279f544b9c4c8b1901a45d19", "Unexpected reviewed baseline"
old = plistlib.loads(baseline_bytes)
new = plistlib.loads(args.candidate.read_bytes())
assert new["#Revision"]["Original-Model"] == "MacBookPro14,2"
assert new["#Revision"]["Build-Type"] == "OpenCore Built on Target Machine"
assert new["#Revision"]["Fork-Profile"] == "rctphone/MacBookPro14,2-quiet-v1"
previous = old["DeviceProperties"]["Add"]
for node, properties in list(new["DeviceProperties"]["Add"].items()):
    if "brcmfx-country" not in properties:
        continue
    if "brcmfx-country" in previous.get(node, {}):
        properties["brcmfx-country"] = previous[node]["brcmfx-country"]
    else:
        del properties["brcmfx-country"]
        if not properties:
            del new["DeviceProperties"]["Add"][node]
assert new["DeviceProperties"] == old["DeviceProperties"], "Other hardware property changes require review"
args.candidate.write_bytes(plistlib.dumps(new, sort_keys=True))
print("Wi-Fi region preserved; hardware properties match reviewed baseline.")
