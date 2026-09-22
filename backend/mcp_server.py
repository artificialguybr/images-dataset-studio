"""MCP stdio server for Images Dataset Studio.

Start the API first, then expose the local REST API to an MCP client with:
`uv run python -m backend.mcp_server`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("IDS_API_URL", "http://127.0.0.1:8766").rstrip("/")
mcp = FastMCP("Images Dataset Studio")


def request(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        headers={"content-type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Studio API returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Studio API unavailable at {API_URL}: {exc.reason}") from exc


@mcp.tool()
def health() -> dict[str, Any]:
    """Check that the Studio API is reachable."""
    return request("/api/health")


@mcp.tool()
def list_datasets() -> list[dict[str, Any]]:
    """List all datasets and their current item counts."""
    return request("/api/datasets")


@mcp.tool()
def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Get one dataset, counts, and processing state."""
    return request(f"/api/datasets/{urllib.parse.quote(dataset_id)}")


@mcp.tool()
def create_dataset(name: str, description: str = "", license: str = "unknown") -> dict[str, Any]:
    """Create a dataset without importing files yet."""
    return request("/api/datasets", "POST", {"name": name, "description": description, "license": license})


@mcp.tool()
def list_items(dataset_id: str, query: str = "", status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """List filtered images in a dataset."""
    params = urllib.parse.urlencode({"q": query, "status": status, "limit": max(1, min(limit, 5000))})
    return request(f"/api/datasets/{urllib.parse.quote(dataset_id)}/items?{params}")


@mcp.tool()
def get_item(item_id: str) -> dict[str, Any]:
    """Get image metadata, issues, labels, and caption."""
    return request(f"/api/items/{urllib.parse.quote(item_id)}")


@mcp.tool()
def set_image_decision(item_id: str, decision: str, reason: str = "") -> dict[str, Any]:
    """Set an image decision: keep, quarantine, reject, or pending."""
    return request(f"/api/items/{urllib.parse.quote(item_id)}/decision", "PATCH", {"decision": decision, "reason": reason})


@mcp.tool()
def start_dataset_job(dataset_id: str, job_type: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a supported dataset job such as quality, deduplication, or captioning."""
    return request(f"/api/datasets/{urllib.parse.quote(dataset_id)}/jobs/{urllib.parse.quote(job_type)}", "POST", config or {})


@mcp.tool()
def get_job(job_id: str) -> dict[str, Any]:
    """Read asynchronous job progress and errors."""
    return request(f"/api/jobs/{urllib.parse.quote(job_id)}")


@mcp.tool()
def export_dataset(dataset_id: str, format: str, version_id: str = "") -> dict[str, Any]:
    """Export a dataset in one of the formats advertised by the REST API."""
    body = {"fmt": format}
    if version_id:
        body["version_id"] = version_id
    return request(f"/api/datasets/{urllib.parse.quote(dataset_id)}/export", "POST", body)


if __name__ == "__main__":
    mcp.run()
