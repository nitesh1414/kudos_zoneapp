"""Broker plug-in registry.

Adding a provider only requires an adapter and one registration here; routes,
admin UI and the EOD worker never import a provider SDK directly.
"""
from dataclasses import dataclass
from typing import Callable

from .base import BrokerAdapter
from .fyers_adapter import FyersAdapter


@dataclass(frozen=True)
class BrokerType:
    key: str
    label: str
    adapter: type[BrokerAdapter]
    fields: tuple[dict, ...]


_TYPES: dict[str, BrokerType] = {}


def register(item: BrokerType):
    _TYPES[item.key] = item


def broker_types():
    return [{"key": x.key, "label": x.label, "fields": list(x.fields)} for x in _TYPES.values()]


def make_broker(kind: str, credentials: dict) -> BrokerAdapter:
    if kind not in _TYPES:
        raise ValueError(f"Unsupported broker type: {kind}")
    return _TYPES[kind].adapter(**credentials)


register(BrokerType(
    key="fyers", label="Fyers", adapter=FyersAdapter,
    fields=(
        {"name": "client_id", "label": "App / Client ID", "secret": False},
        {"name": "access_token", "label": "Access token", "secret": True},
    ),
))
