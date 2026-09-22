"""Small stdlib-only adapters for hosted vision providers.

The provider registry decides *which* service runs. This module only translates
its common image+prompt request into each vendor's HTTP contract.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import get_settings, provider_model


def _image_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode()}"


def _request(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{url} returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach {url}: {exc.reason}") from exc


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "caption", "output"):
            if key in value:
                return _text(value[key])
    return str(value)


def _normalize(payload: Any) -> dict[str, Any]:
    output = payload.get("output", payload) if isinstance(payload, dict) else payload
    if isinstance(output, dict):
        result = dict(output)
        text = _text(output)
    else:
        text = _text(output)
        result = {"text": text}
    result.setdefault("text", text)
    result.setdefault("caption", text)
    if text:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    result.update(parsed)
            except json.JSONDecodeError:
                pass
    return result


def call_vision(provider: str, image_path: str, prompt: str, capability: str) -> dict[str, Any]:
    settings = get_settings()
    image = _image_url(image_path)
    model = provider_model(provider, capability)
    if not model:
        raise RuntimeError(f"no {provider} model configured for {capability}")
    if provider == "replicate":
        payload = _request(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            {"Authorization": f"Bearer {settings.replicate_api_token}", "Prefer": "wait=60"},
            {"input": {"prompt": prompt, "image": image}},
        )
        if payload.get("status") not in {"succeeded", "completed"}:
            raise RuntimeError(f"Replicate prediction did not complete: {payload.get('status', 'unknown')}")
    elif provider == "falai":
        payload = _request(
            f"https://fal.run/{model}",
            {"Authorization": f"Key {settings.fal_api_key}"},
            {"prompt": prompt, "image_url": image},
        )
    else:
        raise ValueError(f"unsupported cloud provider: {provider}")
    return _normalize(payload)
