"""Broker registry. Adding a broker = one adapter file + one line in `_ADAPTERS`."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.brokers.base import BrokerAdapter, BrokerCredentials
from app.brokers.dhan import DhanBroker
from app.brokers.paper import PaperBroker

_ADAPTERS: dict[str, type[BrokerAdapter]] = {
    PaperBroker.key: PaperBroker,
    DhanBroker.key: DhanBroker,
}


class UnknownBroker(KeyError):
    pass


def register(adapter: type[BrokerAdapter]) -> type[BrokerAdapter]:
    _ADAPTERS[adapter.key] = adapter
    return adapter


def get_adapter_class(key: str) -> type[BrokerAdapter]:
    try:
        return _ADAPTERS[key]
    except KeyError:
        raise UnknownBroker(key) from None


def create_adapter(
    key: str, credentials: BrokerCredentials | None = None, *, live_enabled: bool = False
) -> BrokerAdapter:
    return get_adapter_class(key)(credentials, live_enabled=live_enabled)


def available() -> list[dict[str, Any]]:
    """Public description of every broker, used to build the dashboard 'Add broker' form."""
    return [
        {
            "key": a.key,
            "display_name": a.display_name,
            "supports": sorted(a.supports),
            "auth_type": a.auth_type,
            "is_paper": a.is_paper,
            "docs_url": a.docs_url,
            "credential_fields": {
                purpose: [asdict(f) for f in fields]
                for purpose, fields in a.credential_fields.items()
            },
        }
        for a in _ADAPTERS.values()
    ]
