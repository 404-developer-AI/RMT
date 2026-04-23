"""Concrete-adapter registry — maps a provider key to its adapter class.

A concrete adapter registers itself by calling :func:`register_adapter` at
import time. The credentials API's "Test connection" endpoint uses this to
look up which class to instantiate for a given provider.

V1 ships the registry empty — the GoDaddy and Combell adapters land in
follow-up work and will register themselves at that point. Until then,
:func:`get_adapter_class` returns ``None`` and the API surfaces a friendly
"adapter not yet implemented" message.
"""

from __future__ import annotations

from app.registrars.base import RegistrarAdapter

_ADAPTERS: dict[str, type[RegistrarAdapter]] = {}


def register_adapter(cls: type[RegistrarAdapter]) -> type[RegistrarAdapter]:
    """Register a concrete adapter class, keyed by its ``provider`` string."""
    provider = getattr(cls, "provider", None)
    if not isinstance(provider, str) or not provider:
        raise TypeError(
            f"{cls.__name__} must declare a non-empty str `provider` class attribute"
        )
    if provider in _ADAPTERS:
        raise ValueError(f"Adapter already registered for provider {provider!r}")
    _ADAPTERS[provider] = cls
    return cls


def get_adapter_class(provider: str) -> type[RegistrarAdapter] | None:
    """Return the adapter class for ``provider``, or ``None`` if none is registered."""
    return _ADAPTERS.get(provider)


def registered_providers() -> list[str]:
    """Provider keys that currently have a concrete adapter available."""
    return list(_ADAPTERS)
