"""Small, cross-platform JSONL runner for self-contained plugin packs.

Plugins são processos persistentes (um por plugin+capabilidade) que falam
JSONL linha-a-linha; o modelo carrega uma vez por processo, não uma vez por item.
Processos idle além de IDS_PLUGIN_IDLE_TIMEOUT são despejados por um reaper —
RAM/VRAM do modelo voltam pro sistema quando ninguém usa.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .config import get_settings

class PluginError(RuntimeError):
    pass


def _manifest(plugin_id: str) -> tuple[Path, dict[str, Any]]:
    root = (get_settings().plugins_dir / plugin_id).resolve()
    path = root / "manifest.json"
    if not path.is_file():
        raise PluginError("plugin is not installed")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PluginError("plugin manifest is invalid") from exc
    command = data.get("command")
    capabilities = data.get("capabilities", [])
    permissions = data.get("permissions", [])
    allowed_permissions = {"filesystem:input", "filesystem:output", "network:approved", "model:cache"}
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v.startswith("./") for v in command):
        raise PluginError("plugin manifest requires relative ./ command paths")
    if not isinstance(capabilities, list) or not all(isinstance(v, str) for v in capabilities):
        raise PluginError("plugin manifest capabilities are invalid")
    if not isinstance(permissions, list) or any(v not in allowed_permissions for v in permissions):
        raise PluginError("plugin permissions are not allowed")
    root_resolved = root.resolve()
    for value in command:
        if not value.startswith("./"):
            raise PluginError("plugin command must point inside the plugin pack")
        executable = (root / value[2:]).resolve()
        if root_resolved not in executable.parents or not executable.is_file():
            raise PluginError("plugin executable is outside the installed pack or missing")
    return root, data


class _PluginProc:
    """Um processo-plugin vivo. Requisições ao mesmo processo são serializadas
    por lock — inferência é GPU-bound, paralelismo aqui só duplicaria VRAM."""

    def __init__(self, root: Path, manifest: dict[str, Any]):
        self._lock = threading.RLock()
        self.last_used = time.monotonic()
        self._start(root, manifest)
    def _start(self, root: Path, manifest: dict[str, Any]) -> None:
        command = [str(root / value[2:]) if value.startswith("./") else value
                          for value in manifest["command"]]
        self._proc = subprocess.Popen(
            command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, shell=False, bufsize=1,
            env={**os.environ, "IDS_PLUGIN_ROOT": str(root)})

    def call(self, capability: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        self.last_used = time.monotonic()
        request = json.dumps({"protocol": "ids-plugin.v1", "capability": capability,
                             "payload": payload}) + "\n"
        with self._lock:
            if self._proc.poll() is not None:
                raise PluginError("plugin process exited unexpectedly")
            try:
                self._proc.stdin.write(request)
                self._proc.stdin.flush()
                line = self._wait_line(timeout)
            except (BrokenPipeError, OSError) as exc:
                raise PluginError(f"plugin process died: {exc}") from exc
        return self._parse(line)

    def _wait_line(self, timeout: int) -> str:
        # deadline manual: readline() não aceita timeout sem thread extra
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(self._proc.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        buffered = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not sel.select(remaining):
                self.kill()
                raise PluginError("plugin timed out")
            buffered += self._proc.stdout.readline()
            stripped = buffered.strip()
            if stripped:
                return stripped
            if self._proc.poll() is not None:
                raise PluginError("plugin process exited unexpectedly")

    def _parse(self, line: str) -> dict[str, Any]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PluginError(f"plugin returned invalid JSON: {line[:200]}") from exc
        if event.get("type") == "error" or not isinstance(event.get("output"), dict):
            detail = str(event.get("error", ""))[-300:]
            raise PluginError(detail or "plugin returned no result event")
        return event["output"]

    def kill(self) -> None:
        with self._lock:
            try:
                self._proc.kill()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass


_procs: dict[tuple[str, str], _PluginProc] = {}
_procs_lock = threading.Lock()


def _get_proc(plugin_id: str, capability: str) -> _PluginProc:
    key = (plugin_id, capability)
    with _procs_lock:
        proc = _procs.get(key)
        if proc is not None and proc._proc.poll() is None:
            return proc
        if proc is not None:
            _procs.pop(key, None)
    if proc is not None:
        proc.kill()
    root, manifest = _manifest(plugin_id)
    if capability not in manifest.get("capabilities", []):
        raise PluginError(f"plugin does not provide {capability}")
    with _procs_lock:
        current = _procs.get(key)
        if current is not None and current._proc.poll() is None:
            return current
        proc = _PluginProc(root, manifest)
        _procs[key] = proc
        return proc


def shutdown_plugins() -> None:
    """Descarrega todos os processos-plugin (RAM/VRAM liberados)."""
    with _procs_lock:
        procs = list(_procs.values())
        _procs.clear()
    for proc in procs:
        proc.kill()


def _reap_idle() -> None:
    """Despeja processos-plugin idle — o 'unload' de modelos externos."""
    idle = get_settings().plugin_idle_timeout
    if idle <= 0:
        return
    cutoff = time.monotonic() - idle
    with _procs_lock:
        dead = [k for k, p in _procs.items() if p.last_used < cutoff]
        procs = [_procs.pop(k) for k in dead]
    for proc in procs:
        proc.kill()

def _reaper_loop() -> None:
    while True:
        time.sleep(60)
        try:
            _reap_idle()
        except Exception:  # noqa: BLE001 — reaper nunca pode derrubar o app
            pass


threading.Thread(target=_reaper_loop, daemon=True).start()
atexit.register(shutdown_plugins)


def invoke(plugin_id: str, capability: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    proc = _get_proc(plugin_id, capability)
    try:
        return proc.call(capability, payload, timeout)
    except PluginError:
        # processo pode ter morrido/entrado em estado ruim: derruba, próxima chamada sobe de novo
        with _procs_lock:
            dead = _procs.pop((plugin_id, capability), None)
        if dead is not None:
            dead.kill()
        raise
