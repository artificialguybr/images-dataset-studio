"""Shared path helpers for item URIs.

source_uri schemes: 'local:', 'imported:', 'retried:', 'file:' prefix a filesystem
path. A bare path (including a Windows drive 'C:\\...') is used as-is.
"""
from pathlib import Path
from ..models import ImageItem

_SCHEMES = ("local:", "imported:", "retried:", "file:")


def item_path(it: ImageItem) -> Path:
    uri = it.source_uri
    for scheme in _SCHEMES:
        if uri.startswith(scheme):
            uri = uri[len(scheme):]
            break
    path = Path(uri)
    if not path.is_file() and ":/" in uri:
        # Repair legacy imports that concatenated an absolute path after a colon.
        candidate = Path("/" + uri.rsplit(":/", 1)[-1].lstrip("/"))
        if candidate.is_file():
            path = candidate
    return path.resolve()
