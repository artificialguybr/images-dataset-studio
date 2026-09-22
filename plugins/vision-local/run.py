#!/usr/bin/env python3
"""Plugin entrypoint: bootstrap vendored wheels, then hand off to the handler."""
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

VENDOR = HERE / "vendor"
if VENDOR.is_dir():
    _py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    extract = Path(tempfile.gettempdir()) / f"ids-vendor-{VENDOR.stat().st_mtime_ns}-{_py}"
    if not extract.is_dir():
        extract.mkdir(parents=True, exist_ok=True)
        for whl in VENDOR.glob("*.whl"):
            # wheel name: name-version-pythontag-abitag-platform.whl
            parts = whl.stem.split("-")
            if len(parts) >= 3:
                pytag, abi = parts[-3], parts[-2]
                ok = abi == "abi3" or pytag in (_py, "py3", f"py{sys.version_info.major}", "none")
                if not ok:
                    continue  # wheel built for a different python; skip
            zipfile.ZipFile(whl).extractall(extract)
    sys.path.insert(0, str(extract))

SHARED = next(p for p in (HERE / "_shared", HERE.parent / "_shared") if p.is_dir())
sys.path.insert(0, str(SHARED))

from vision import main  # noqa: E402

if __name__ == "__main__":
    main()
