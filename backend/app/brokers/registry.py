"""Broker plug-in registry.

Adding a provider only requires an adapter and one registration here; routes,
admin UI and the EOD worker never import a provider SDK directly.
"""
import os
from dataclasses import dataclass
from typing import Callable

from dotenv import load_dotenv

from .base import BrokerAdapter
from .fyers_adapter import FyersAdapter

load_dotenv()


@dataclass(frozen=True)
class BrokerType:
    key: str
    label: str
    adapter: type[BrokerAdapter]
    fields: tuple[dict, ...]
    token_ttl_hours: int | None = None
    defaults: dict | None = None


INDIA_CANDLE_RESOLUTIONS = ("1", "2", "3", "5", "10", "15", "20", "30", "45", "60", "120", "180", "240", "D")

_TYPES: dict[str, BrokerType] = {}


def register(item: BrokerType):
    _TYPES[item.key] = item


def broker_types():
    return [{"key": x.key, "label": x.label, "fields": list(x.fields),
             "token_ttl_hours": x.token_ttl_hours,
             "defaults": x.defaults,
             "resolutions": list(INDIA_CANDLE_RESOLUTIONS)} for x in _TYPES.values()]


def get_broker_type(kind: str) -> BrokerType:
    if kind not in _TYPES:
        raise ValueError(f"Unsupported broker type: {kind}")
    return _TYPES[kind]


def make_broker(kind: str, credentials: dict) -> BrokerAdapter:
    if kind not in _TYPES:
        raise ValueError(f"Unsupported broker type: {kind}")
    return _TYPES[kind].adapter(**credentials)


# Fyers is the default broker. Access token is optional at creation time;
# it can be added later via the token generation flow. The client_id and
# secret are pre-filled from environment variables when available.
register(BrokerType(
    key="fyers", label="Fyers", adapter=FyersAdapter,
    fields=(
        {"name": "client_id", "label": "App / Client ID", "secret": False, "default": os.getenv("FYERS_CLIENT_ID", "")},
        {"name": "access_token", "label": "Access token", "secret": True, "required": False},
    ),
    token_ttl_hours=24,
    defaults={
        "client_id": os.getenv("FYERS_CLIENT_ID", ""),
        "secret_key": os.getenv("FYERS_SECRET_KEY", ""),
        "redirect_uri": os.getenv("FYERS_REDIRECT_URI", "https://fyers.in/"),
    },
))
