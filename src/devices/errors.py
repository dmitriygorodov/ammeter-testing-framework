class AmmeterClientError(RuntimeError):
    """Base class for client-side ammeter failures."""


class AmmeterConnectionError(AmmeterClientError):
    """A transport connection could not be established or was interrupted."""


class AmmeterTimeoutError(AmmeterClientError):
    """An ammeter operation did not finish within its deadline."""


class AmmeterProtocolError(AmmeterClientError):
    """An ammeter request or response violated the wire protocol."""


class AmmeterRegistryError(ValueError):
    """Base class for invalid ammeter registry operations."""


class DuplicateAmmeterError(AmmeterRegistryError):
    """Two devices use the same normalized registry name."""


class UnknownAmmeterError(KeyError):
    """A requested ammeter is not present in the registry."""
