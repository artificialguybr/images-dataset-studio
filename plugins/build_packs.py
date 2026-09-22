#!/usr/bin/env python3
"""Build self-contained .pluginpack archives for the official local plugins.

Vendor wheels for the plugin runtimes into each pack so the packs run without
any pip install on the user machine (decision: self-contained packs).

Usage: python3 plugins/build_packs.py [--skip-vendor]
"""
import argparse
import json
import platform as host_platform
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR_PKGS = {
    "privacy-local": ["onnxruntime", "ai-edge-litert", "numpy", "pillow", "opencv-python-headless"],
    "vision-local": ["onnxruntime", "numpy", "pillow", "opencv-python-headless"],
}
FILES = {
    "privacy-local": ["manifest.json", "run.py", "ocr.py", "charset.json"],
    "vision-local": ["manifest.json", "run.py", "vision.py"],
}


def host_platform_tag() -> str:
    machine = host_platform.machine().lower()
    if host_platform.system() == "Darwin":
        return "macos-arm64" if machine == "arm64" else "macos-x64"
    if host_platform.system() == "Linux":
        return "linux-x64" if machine in ("x86_64", "amd64") else "linux-arm64"
    return "windows-x64" if host_platform.system() == "Windows" else "unknown"
# target matrix: (tag, pip --platform, --python-version, --abi)
TARGETS = {
    "macos-arm64": (["macosx_11_0_arm64"], "3.12"),
    "macos-x64": (["macosx_10_13_x86_64", "macosx_11_0_x86_64"], "3.12"),
    "linux-x64": (["manylinux_2_27_x86_64", "manylinux_2_28_x86_64"], "3.12"),
    "windows-x64": (["win_amd64"], "3.12"),
}
ABIS = ["cp312", "abi3", "none"]

def vendor(plugin_id: str, target: Path, tgt: str | None = None) -> None:
    pip_platforms, pyver = TARGETS.get(tgt, (None, None)) if tgt else (None, None)
    for pkg in VENDOR_PKGS[plugin_id]:
        cmd = [sys.executable, "-m", "pip", "download", pkg, "--no-deps", "-d", str(target)]
        if tgt:
            cmd += [arg for p in pip_platforms for arg in ("--platform", p)]
            cmd += ["--python-version", pyver, "--implementation", "cp",
                    "--only-binary=:all:"]
            cmd += [arg for abi in ABIS for arg in ("--abi", abi)]
        subprocess.run(cmd, check=True, capture_output=True)


def build(plugin_id: str, skip_vendor: bool, tgt: str | None = None) -> Path:
    plugin_dir = ROOT / plugin_id
    suffix = f"-{tgt}" if tgt else ""
    pack = ROOT / f"{plugin_id}{suffix}.pluginpack"
    vendor_dir = plugin_dir / ("vendor" if not tgt else f"vendor-{tgt}")
    with zipfile.ZipFile(pack, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES[plugin_id]:
            if name == "manifest.json":
                manifest = json.loads((plugin_dir / name).read_text())
                manifest["platforms"] = [tgt] if tgt else [host_platform_tag()]
                archive.writestr(name, json.dumps(manifest, indent=2))
            else:
                archive.write(plugin_dir / name, name)
        archive.write(ROOT / "_shared" / "inference.py", "_shared/inference.py")
        if not skip_vendor:
            vendor(plugin_id, vendor_dir, tgt)
        if vendor_dir.is_dir():
            for wheel in vendor_dir.glob("*.whl"):
                archive.write(wheel, f"vendor/{wheel.name}")
    return pack


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-vendor", action="store_true",
                        help="pack code only; wheels are added separately")
    parser.add_argument("--target", choices=list(TARGETS) + ["all"], default=None,
                        help="build wheels for one platform tag, 'all', or the current host")
    args = parser.parse_args()
    tgts = list(TARGETS) if args.target == "all" else ([args.target] if args.target else [None])
    for plugin_id in FILES:
        for tgt in tgts:
            pack = build(plugin_id, args.skip_vendor, tgt)
            print(f"built {pack.name} ({pack.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    main()
