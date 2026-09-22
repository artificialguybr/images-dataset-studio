"""Catalog and lifecycle for optional model/plugin assets.

The core stores metadata and never imports a model runtime. Model files and
plugin executables are installed separately; inference remains behind the
provider/plugin protocol.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import platform
import shutil
import sys
import tempfile
import threading
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import get_settings


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    capability: str
    plugin_id: str
    description: str
    license: str
    size_mb: int
    source_url: str = ""
    revision: str = ""
    runtime: str = "onnx"
    platforms: tuple[str, ...] = ("linux", "macos", "windows")
    installable: bool = True
    memory_mb: int = 512
    # turnkey sources: url + target filename + pinned sha256; install needs no user checksum
    sources: tuple[dict[str, str], ...] = ()
    install_hint: str = ""
    recommended: bool = False
    quality_tier: str = "balanced"
    selection_reason: str = ""

PERMISSIVE_LICENSES = {"Apache-2.0", "MIT", "BSD-3-Clause", "BSD-2-Clause", "ISC"}

CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec("mobileclip2-s0", "MobileCLIP2-S0", "embedding", "vision-local",
              "Fast image/text embeddings", "Apple AMLR", 286,
              "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s0/vision_model.onnx",
              "ba95759a5bdbaca53e9111e2550a76ec09c8fd9e", "onnx", memory_mb=768,
              sources=(
                  {"url": "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s0/vision_model.onnx", "filename": "clip_image.onnx", "sha256": "13d20ebfa8a8f63890eb2727fe4dc63009ff970f43e0f7d9d2ed999659f70c8a"},
                  {"url": "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s0/text_model.onnx", "filename": "clip_text.onnx", "sha256": "df590d47744f2ee9f3ccb67c4414d17419568c05bca0c4d166f2faeedf8b92f3"},
              ), recommended=True, quality_tier="small",
              selection_reason="Smallest verified image/text pair with acceptable retrieval quality; Apple AMLR requires acceptance."),
    ModelSpec("mobileclip2-s2", "MobileCLIP2-S2", "embedding", "vision-local",
              "Higher-quality image/text embeddings", "Apple AMLR", 379,
              "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s2/vision_model.onnx",
              "ba95759a5bdbaca53e9111e2550a76ec09c8fd9e", "onnx", memory_mb=1024,
              sources=(
                  {"url": "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s2/vision_model.onnx", "filename": "clip_image.onnx", "sha256": "a841f72c5a5085748bbe271a1d5718aba877822a15cba865bdbd0d37036b849e"},
                  {"url": "https://huggingface.co/plhery/mobileclip2-onnx/resolve/ba95759a5bdbaca53e9111e2550a76ec09c8fd9e/onnx/s2/text_model.onnx", "filename": "clip_text.onnx", "sha256": "622f10372bca71b5017f2efc5f8c2886610a2592b636de8984d717f03213f031"},
              ), quality_tier="quality", selection_reason="Larger MobileCLIP2 option when retrieval quality matters more than download size."),
    ModelSpec("openclip-vit-b32", "OpenCLIP ViT-B/32", "embedding", "vision-local",
              "Existing OpenCLIP semantic search provider", "MIT", 350, "", "main", "torch", memory_mb=1024,
              quality_tier="legacy", selection_reason="Compatibility fallback for the existing Torch provider."),
    ModelSpec("florence-2-base-ft", "Florence-2 base", "preannotation", "vision-local",
              "Boxes, labels, OCR and region prompts", "MIT", 930,
              "", "main", "transformers", memory_mb=2048,
              install_hint="HF has an ONNX community export with encoder/decoder/vision files, but this plugin still requires a converted florence2.onnx bundle. Use advanced install only after conversion.",
              recommended=True, quality_tier="quality", selection_reason="Best broad preannotation quality in the current catalog; larger and requires conversion."),
    ModelSpec("florence-2-caption", "Florence-2 captioning", "captioning", "vision-local",
              "Prompted image captions for training datasets", "MIT", 930,
              "", "main", "onnx", memory_mb=2048,
              install_hint="Requires a compatible Florence-2 captioning ONNX bundle installed through Extensions.",
              recommended=True, quality_tier="quality", selection_reason="Broad prompted captioning model; requires a compatible local ONNX export."),
    ModelSpec("pp-ocrv5-mobile", "PP-OCRv5 mobile", "ocr", "privacy-local",
              "CPU-oriented text detection and recognition", "Apache-2.0", 21,
              "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/e6f4fa85f00e168c862bc462aebca69eef9b3d3d/inference.onnx",
              "e6f4fa85f00e168c862bc462aebca69eef9b3d3d", "onnx", memory_mb=512,
              sources=(
                  {"url": "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/e6f4fa85f00e168c862bc462aebca69eef9b3d3d/inference.onnx", "filename": "pp_ocrv5_det.onnx", "sha256": "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d"},
                  {"url": "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_rec_onnx/resolve/ed152b8b495f84de93cda5709d768548a9127622/inference.onnx", "filename": "pp_ocrv5_rec.onnx", "sha256": "da72dc72ca4dc220df0dfde68c1dedc31c58d3e76a25871122e5056227d50092"},
              ), recommended=True, quality_tier="small", selection_reason="Small CPU pair with strong multilingual OCR trade-off."),
    ModelSpec("blazeface-short-range", "MediaPipe BlazeFace", "pii", "privacy-local",
              "On-device face detection", "Apache-2.0", 6,
              "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
              "latest", "tflite", memory_mb=256,
              sources=({"url": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite", "filename": "blaze_face_short_range.tflite", "sha256": "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"},),
              recommended=True, quality_tier="small", selection_reason="Tiny offline face detector; broader PII classes require an additional opt-in provider."),
    ModelSpec("mobile-sam", "MobileSAM", "segmentation", "vision-local",
              "Interactive masks from boxes or points", "MIT", 45,
              "https://huggingface.co/Acly/MobileSAM/resolve/main/mobile_sam_image_encoder.onnx",
              "main", "onnx", memory_mb=1024,
              sources=(
                  {"url": "https://huggingface.co/Acly/MobileSAM/resolve/main/mobile_sam_image_encoder.onnx", "filename": "sam_encoder.onnx", "sha256": "580f5fb648ea1062c0aabc26217aed56921985f03f0cbbd852bba81d760cc749"},
                  {"url": "https://huggingface.co/Acly/MobileSAM/resolve/main/sam_mask_decoder_single.onnx", "filename": "sam_decoder.onnx", "sha256": "93915fc7c993ab9d59ab8c9ccd3bce37f7509c81ab4150a74abd4d2abbd8570d"},
              ), recommended=True, quality_tier="small", selection_reason="Small interactive mask model with a verified ONNX encoder/decoder pair; checksum-pinned HF files."),
    ModelSpec("yolox-nano", "YOLOX-Nano", "detection", "vision-local",
              "Small permissive COCO detector", "Apache-2.0", 4,
              "https://huggingface.co/Heliosoph/yolox-onnx/resolve/9206d80cbad9ed54986edeff8d7457eb5333882a/yolox_nano.onnx",
              "9206d80cbad9ed54986edeff8d7457eb5333882a", "onnx", memory_mb=512,
              sources=({"url": "https://huggingface.co/Heliosoph/yolox-onnx/resolve/9206d80cbad9ed54986edeff8d7457eb5333882a/yolox_nano.onnx", "filename": "yolox_nano.onnx", "sha256": "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"},),
              recommended=True, quality_tier="small", selection_reason="Smallest verified COCO detector; use a larger YOLOX variant for recall."),
    ModelSpec("yolox-tiny", "YOLOX-Tiny", "detection", "vision-local",
              "Higher-recall COCO detector", "Apache-2.0", 20,
              "https://huggingface.co/Heliosoph/yolox-onnx/resolve/9206d80cbad9ed54986edeff8d7457eb5333882a/yolox_tiny.onnx",
              "9206d80cbad9ed54986edeff8d7457eb5333882a", "onnx", memory_mb=768,
              sources=({"url": "https://huggingface.co/Heliosoph/yolox-onnx/resolve/9206d80cbad9ed54986edeff8d7457eb5333882a/yolox_tiny.onnx", "filename": "yolox_nano.onnx", "sha256": "bdfb504443b3f39018a533d810a3d1badc0c0ba45681db1a3b0d423443143132"},),
              quality_tier="quality", selection_reason="Larger COCO detector option; same plugin contract, higher download and memory."),
    ModelSpec("openai-vision", "OpenAI Vision", "preannotation", "cloud-vision",
              "Cloud multimodal provider", "Provider terms", 0, "", "configured", "https", installable=False),
    ModelSpec("openai-vision-pii", "OpenAI Vision for PII", "pii", "cloud-vision",
              "Cloud PII scan provider", "Provider terms", 0, "", "configured", "https", installable=False),
)

_LOCK = threading.Lock()


def _settings_path() -> Path:
    s = get_settings()
    path = s.models_dir / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_state() -> dict[str, Any]:
    path = _settings_path()
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"models": {}, "active": {}, "plugins": {}, "automation": {}}


def _write_state(state: dict[str, Any]) -> None:
    path = _settings_path()
    fd, temp = tempfile.mkstemp(prefix="state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
def get_model(model_id: str) -> ModelSpec:
    return _spec(model_id)


def plugin_installed(plugin_id: str) -> bool:
    return (get_settings().plugins_dir / plugin_id / "manifest.json").is_file()

def read_settings() -> dict[str, Any]:
    return _read_state()

def installed_path(model_id: str) -> str:
    # plugins run with cwd inside their own pack: absolute model path
    return str(Path(_read_state().get("models", {}).get(model_id, {}).get("path", "")).resolve())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spec(model_id: str) -> ModelSpec:
    for item in CATALOG:
        if item.id == model_id:
            return item
    raise KeyError(model_id)


def list_catalog() -> list[dict[str, Any]]:
    state = _read_state()
    models = state.get("models", {})
    return [{**asdict(spec), "platforms": list(spec.platforms),
             "status": models.get(spec.id, {}).get("status", "not_installed"),
             "installed": models.get(spec.id, {}).get("status") == "installed",
             "active": state.get("active", {}).get(spec.capability) == spec.id,
             "installed_path": models.get(spec.id, {}).get("path", ""),
             "sha256": models.get(spec.id, {}).get("sha256", ""),
             "error": models.get(spec.id, {}).get("error", "")}
            for spec in CATALOG]


def plugins() -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    for manifest in s.plugins_dir.glob("*/manifest.json"):
        try:
            data = json.loads(manifest.read_text())
            out.append({**data, "installed": True, "path": str(manifest.parent)})
        except (OSError, json.JSONDecodeError):
            continue
    return out


def set_active(capability: str, model_id: str) -> dict[str, Any]:
    spec = _spec(model_id)
    if spec.capability != capability:
        raise ValueError("model capability mismatch")
    state = _read_state()
    if state.get("models", {}).get(model_id, {}).get("status") != "installed":
        raise ValueError("model is not installed")
    state.setdefault("active", {})[capability] = model_id
    _write_state(state)
    return {"capability": capability, "model_id": model_id}

def set_automation(capability: str, enabled: bool, confidence: float = 0.95,
                    preview: bool = True, auto_quarantine: bool = False) -> dict[str, Any]:
    state = _read_state()
    state.setdefault("automation", {})[capability] = {
        "enabled": bool(enabled),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "preview": bool(preview),
        "auto_quarantine": bool(auto_quarantine),
    }
    _write_state(state)
    return state["automation"][capability]


def active_model(capability: str) -> str | None:
    return _read_state().get("active", {}).get(capability)


def _finish_turnkey_install(model_id: str) -> None:
    state = _read_state()
    try:
        spec = _spec(model_id)
        models_dir = get_settings().models_dir.resolve()
        target_dir = models_dir / model_id / (spec.revision or "default")
        if target_dir.exists():
            shutil.rmtree(target_dir)  # reinstall starts clean; no stale artifacts
        target_dir.mkdir(parents=True, exist_ok=True)
        digests = []
        for src in spec.sources:
            filename = Path(src["filename"]).name  # never trust paths from specs
            dest = target_dir / filename
            with urllib.request.urlopen(src["url"], timeout=120) as response, dest.open("wb") as out:
                shutil.copyfileobj(response, out)
            digest = _sha256(dest)
            if digest.lower() != src["sha256"].lower():
                dest.unlink(missing_ok=True)
                raise ValueError(f"SHA-256 mismatch for {filename}; model was not installed")
            digests.append(digest)
        state.setdefault("models", {})[model_id] = {
            "status": "installed", "path": str(target_dir / spec.sources[0]["filename"]),
            "sha256": digests[0], "turnkey": True}
    except Exception as exc:  # noqa: BLE001 — persisted for UI diagnosis
        state.setdefault("models", {})[model_id] = {"status": "failed", "error": str(exc)[:500]}
    finally:
        with _LOCK:
            _write_state(state)


def _finish_install(model_id: str, source: str, sha256: str) -> None:
    state = _read_state()
    try:
        spec = _spec(model_id)
        models_dir = get_settings().models_dir.resolve()
        target_dir = models_dir / model_id / (spec.revision or "default")
        target_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=models_dir) as tmp:
            tmp_path = Path(tmp) / "model.asset"
            if source.startswith(("https://", "http://")):
                if not source.startswith("https://"):
                    raise ValueError("model downloads require HTTPS")
                with urllib.request.urlopen(source, timeout=30) as response, tmp_path.open("wb") as out:
                    shutil.copyfileobj(response, out)
            else:
                src = Path(source).expanduser().resolve()
                if not src.is_file():
                    raise ValueError("source_path must point to a model file")
                shutil.copy2(src, tmp_path)
            digest = _sha256(tmp_path)
            if digest.lower() != sha256.lower():
                raise ValueError("SHA-256 mismatch; model was not installed")
            if source.endswith(".zip"):
                # multi-artifact model (e.g. OCR det+rec): extract every member
                import zipfile
                with zipfile.ZipFile(tmp_path) as archive:
                    for member in archive.namelist():
                        member_path = Path(member)
                        if member_path.is_absolute() or ".." in member_path.parts:
                            raise ValueError("model archive contains unsafe paths")
                        archive.extract(member, target_dir)
                target = target_dir / "model.zip"
            else:
                target = target_dir / "model.asset"
            if not source.endswith(".zip"):
                os.replace(tmp_path, target)
        state.setdefault("models", {})[model_id] = {"status": "installed", "path": str(target), "sha256": digest}
    except Exception as exc:  # noqa: BLE001 — persisted for UI diagnosis
        state.setdefault("models", {})[model_id] = {"status": "failed", "error": str(exc)[:500]}
    with _LOCK:
        _write_state(state)


def install_model(model_id: str, source: str = "", sha256: str = "",
                  license_ack: bool = False) -> dict[str, Any]:
    spec = _spec(model_id)
    if spec.license not in PERMISSIVE_LICENSES and not license_ack:
        raise ValueError(f"license '{spec.license}' requires explicit acknowledgement (license_ack)")
    turnkey = not source
    if turnkey and not spec.sources:
        raise ValueError("this model has no turnkey source; use advanced install with a local file and checksum")
    if not turnkey and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256 or ""):
        raise ValueError("a 64-character SHA-256 is required before download")
    state = _read_state()
    state.setdefault("models", {})[model_id] = {"status": "installing"}
    _write_state(state)
    if turnkey:
        thread = threading.Thread(target=_finish_turnkey_install, args=(model_id,), daemon=True)
    else:
        thread = threading.Thread(target=_finish_install, args=(model_id, source, sha256), daemon=True)
    thread.start()
    return {"model_id": model_id, "status": "installing"}


def uninstall_model(model_id: str) -> dict[str, Any]:
    state = _read_state()
    active_caps = [cap for cap, mid in state.get("active", {}).items() if mid == model_id]
    if active_caps:
        raise ValueError(f"model is active for: {', '.join(active_caps)}")
    entry = state.get("models", {}).pop(model_id, None)
    if entry and entry.get("path"):
        shutil.rmtree(Path(entry["path"]).parent, ignore_errors=True)
    _write_state(state)
    return {"model_id": model_id, "status": "not_installed"}



def _host_platform_tag() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "darwin":
        return "macos-arm64" if machine == "arm64" else "macos-x64"
    if system == "linux":
        return "linux-x64" if machine in ("x86_64", "amd64") else "linux-arm64"
    if system == "win32":
        return "windows-x64"
    return f"{system}-{machine}"


def install_plugin(path: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pluginpack":
        raise ValueError("plugin path must be a .pluginpack file")
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if "manifest.json" not in names or any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("invalid plugin manifest or archive paths")
        manifest = json.loads(archive.read("manifest.json"))
        declared = manifest.get("platforms")
        host = _host_platform_tag()
        if isinstance(declared, list) and declared and host not in declared:
            raise ValueError(f"plugin supports {', '.join(declared)}; this machine is {host}")
        plugin_id = str(manifest.get("id", "")).strip()
        if not plugin_id or manifest.get("protocol") != "ids-plugin.v1":
            raise ValueError("plugin manifest requires id and ids-plugin.v1 protocol")
        if not isinstance(manifest.get("command"), list) or not manifest["command"] or not all(
            isinstance(command, str) and command.startswith("./") for command in manifest["command"]):
            raise ValueError("plugin manifest commands must be relative ./ paths")
        permissions = manifest.get("permissions", [])
        allowed_permissions = {"filesystem:input", "filesystem:output", "network:approved", "model:cache"}
        if not isinstance(permissions, list) or any(permission not in allowed_permissions for permission in permissions):
            raise ValueError("plugin permissions must use the declared least-privilege scopes")
        target = get_settings().plugins_dir / plugin_id
        temp = Path(tempfile.mkdtemp(dir=get_settings().plugins_dir))
        try:
            archive.extractall(temp)
            for command in manifest["command"]:
                if isinstance(command, str) and command.startswith("./"):
                    executable = temp / command[2:]
                    if not executable.is_file():
                        raise ValueError(f"plugin command not found: {command}")
                    executable.chmod(executable.stat().st_mode | 0o111)
            if target.exists():
                shutil.rmtree(target)
            os.replace(temp, target)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise
    state = _read_state()
    state.setdefault("plugins", {})[plugin_id] = {"status": "installed", "version": manifest.get("version", "")}
    _write_state(state)
    return {**manifest, "installed": True, "path": str(target)}

def uninstall_plugin(plugin_id: str) -> dict[str, Any]:
    root = (get_settings().plugins_dir / plugin_id).resolve()
    plugins_root = get_settings().plugins_dir.resolve()
    if plugins_root not in root.parents or not (root / "manifest.json").is_file():
        raise KeyError(plugin_id)
    shutil.rmtree(root)
    state = _read_state()
    state.setdefault("plugins", {}).pop(plugin_id, None)
    _write_state(state)
    return {"id": plugin_id, "installed": False}
