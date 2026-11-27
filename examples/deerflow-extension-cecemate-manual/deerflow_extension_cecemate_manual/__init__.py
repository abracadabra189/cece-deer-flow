"""Offline, read-only CeCeMate product manual knowledge provider."""

from deerflow_extension_api import extension

from .config import Settings
from .corpus import Corpus
from .provider import CecemateManualProvider


@extension(api="0.2.7", name="cecemate-manual")
def install(registry, config):
    settings = Settings.from_config(config)
    provider = CecemateManualProvider(Corpus.load(), settings)
    if not registry.knowledge_provider("cecemate-manual", provider):
        raise RuntimeError("This host does not support knowledge provider registration")
