"""Plugin de providers — cada escopo tem N providers; o ativo é escolhido por config/env.

Regra (§15 do plano): provider indisponível => status honesto + instrução,
nunca resultado falso. Adicionar um provider novo = criar uma classe e chamar
`register()` — nenhum outro arquivo precisa mudar.
"""
from abc import ABC, abstractmethod


class Provider(ABC):
    """Contrato mínimo: identidade + disponibilidade honesta."""
    scope: str = ""
    name: str = ""
    version: str = ""
    install: str = ""  # instrução exibida quando indisponível

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Retorna (disponível?, mensagem de setup/instrução)."""


_registry: dict[str, dict[str, Provider]] = {}


def register(p: Provider) -> None:
    _registry.setdefault(p.scope, {})[p.name] = p


def all_for(scope: str) -> dict[str, Provider]:
    return _registry.get(scope, {})

def active(scope: str) -> Provider | None:
    """Provider ativo; seleção do catálogo ganha prioridade quando há adapter."""
    from ..config import get_settings
    from ..model_catalog import active_model
    s = get_settings()
    cands = _registry.get(scope, {})
    capability = {"embeddings": "embedding"}.get(scope, scope)
    selected = active_model(capability)
    provider_for_model = {
        "openclip-vit-b32": "openclip",
        "openai-vision": "openai_vision",
        "openai-vision-pii": "openai_vision",
    }.get(selected or "")
    if provider_for_model in cands:
        return cands[provider_for_model]
    pref = getattr(s, f"{scope}_provider", "") or ""
    if pref and pref in cands:
        return cands[pref]
    return next(iter(cands.values())) if cands else None


def status() -> list[dict]:
    out = []
    for scope, cands in _registry.items():
        act = active(scope)
        for name, p in cands.items():
            ok, msg = p.available()
            out.append({"scope": scope, "name": name, "version": p.version,
                        "active": act is p, "available": ok,
                        "setup": msg or p.install})
    return out
