"""Explicit adapter registration; no plugin discovery or background network access."""
from .base import Provider,Providers,Resolution
from .local import LocalAssetProvider,FakeProvider
from .polyhaven import PolyHavenProvider


def default_providers():
    return Providers(PolyHavenProvider(),LocalAssetProvider())
