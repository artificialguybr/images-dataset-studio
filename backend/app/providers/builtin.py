"""Built-in providers.

Local OpenCLIP, optional Cleanlab, and configurable OpenAI, Replicate, and
fal.ai vision adapters are registered here. New company runtimes can register
the same Provider contract without changing the core services.
"""
from ..analyzers import embeddings as openclip_mod
from .base import Provider, register


class OpenClipProvider(Provider):
    scope = "embeddings"
    name = "openclip"
    version = "1"
    install = "uv sync --extra ml"

    def available(self) -> tuple[bool, str]:
        return openclip_mod.is_available(), self.install


class OpenAIVisionProvider(Provider):
    """Paid vision provider; key and model are configured per capability."""
    version = "1"
    install = "set IDS_OPENAI_API_KEY and a model in Settings"

    def available(self) -> tuple[bool, str]:
        from ..config import get_settings, provider_model
        s = get_settings()
        if not s.openai_api_key:
            return False, self.install
        if not provider_model("openai_vision", self.scope):
            return False, "choose a model in Settings"
        return True, ""


class RemoteVisionProvider(Provider):
    """Base for hosted model APIs configured from Settings or environment."""
    version = "1"

    def available(self) -> tuple[bool, str]:
        from ..config import get_settings, provider_model
        s = get_settings()
        key = getattr(s, self.key_field)
        if not key:
            return False, self.install
        if not provider_model(self.name, self.scope):
            return False, "choose a model in Settings"
        return True, ""


class PreannotationOpenAI(OpenAIVisionProvider):
    scope = "preannotation"
    name = "openai_vision"


class CaptionOpenAI(OpenAIVisionProvider):
    scope = "captioning"
    name = "openai_vision"


class PiiOpenAI(OpenAIVisionProvider):
    scope = "pii"
    name = "openai_vision"


class ReplicatePreannotation(RemoteVisionProvider):
    scope = "preannotation"
    name = "replicate"
    key_field = "replicate_api_token"
    install = "set a Replicate token and model in Settings"


class ReplicateCaption(RemoteVisionProvider):
    scope = "captioning"
    name = "replicate"
    key_field = "replicate_api_token"
    install = "set a Replicate token and model in Settings"


class ReplicatePii(RemoteVisionProvider):
    scope = "pii"
    name = "replicate"
    key_field = "replicate_api_token"
    install = "set a Replicate token and model in Settings"


class FalPreannotation(RemoteVisionProvider):
    scope = "preannotation"
    name = "falai"
    key_field = "fal_api_key"
    install = "set a fal.ai key and model in Settings"


class FalCaption(RemoteVisionProvider):
    scope = "captioning"
    name = "falai"
    key_field = "fal_api_key"
    install = "set a fal.ai key and model in Settings"


class FalPii(RemoteVisionProvider):
    scope = "pii"
    name = "falai"
    key_field = "fal_api_key"
    install = "set a fal.ai key and model in Settings"

class CleanlabProvider(Provider):
    scope = "label_issues"
    name = "cleanlab"
    version = "1"
    install = "uv add cleanlab"

    def available(self) -> tuple[bool, str]:
        try:
            import cleanlab  # noqa: F401
            return True, ""
        except ImportError:
            return False, self.install


register(OpenClipProvider())
for provider in (
    PreannotationOpenAI(), CaptionOpenAI(), PiiOpenAI(),
    ReplicatePreannotation(), ReplicateCaption(), ReplicatePii(),
    FalPreannotation(), FalCaption(), FalPii(),
):
    register(provider)
register(CleanlabProvider())
