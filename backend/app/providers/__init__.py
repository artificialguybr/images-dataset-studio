"""Importar este pacote registra os providers builtin. Plugins externos:
crie um módulo com subclasses de Provider + register() e importe-o aqui."""
from . import builtin  # noqa: F401 — efeito colateral: registro
