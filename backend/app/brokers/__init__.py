"""
brokers/ — one file per broker, each implementing BrokerAdapter (base.py).

No broker is chosen yet. csv_adapter.py is the only implementation right
now and needs no credentials — it's what lets the whole app be built and
tested before that decision is made. See DEVELOPER_BIBLE.md §5.
"""
from .base import BrokerAdapter, BrokerError, AuthStatus
from .fyers_adapter import FyersAdapter