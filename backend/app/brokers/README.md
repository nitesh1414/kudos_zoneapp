# Adding a broker provider

The API, worker and UI depend only on `BrokerAdapter`; they do not contain
Fyers-specific branches.

1. Add `brokers/<name>_adapter.py` and implement every method in `base.py`.
2. Keep the provider SDK import inside that adapter.
3. Accept credentials as constructor keyword arguments. Do not hardcode or
   write credentials to files.
4. Add a `BrokerType` entry in `registry.py`. Its `fields` metadata is used by
   the admin UI to build the connection form.
5. Verify profile/auth, several historical candles and symbol mapping against
   the provider's own platform before enabling the EOD worker.

A user can then add any number of connections for the registered provider and
assign them to clients without code or deployment changes. An entirely new
provider still needs an adapter because authentication and response formats
are not standardized across brokers.
