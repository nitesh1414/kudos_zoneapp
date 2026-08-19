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
    token_ttl_hours: int | None = None


INDIA_CANDLE_RESOLUTIONS = ("1", "2", "3", "5", "10", "15", "20", "30", "45", "60", "120", "180", "240", "D")

_TYPES: dict[str, BrokerType] = {}


def register(item: BrokerType):
    _TYPES[item.key] = item


def broker_types():
    return [{"key": x.key, "label": x.label, "fields": list(x.fields),
             "token_ttl_hours": x.token_ttl_hours,
             "resolutions": list(INDIA_CANDLE_RESOLUTIONS)} for x in _TYPES.values()]


def get_broker_type(kind: str) -> BrokerType:
    if kind not in _TYPES:
        raise ValueError(f"Unsupported broker type: {kind}")
    return _TYPES[kind]


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
    token_ttl_hours=24,
))
