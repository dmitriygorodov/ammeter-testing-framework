"""Unified ammeter device and transport abstractions."""

from .ammeter import SocketAmmeter
from .contracts import Ammeter, MeasurementTransport
from .errors import (
    AmmeterClientError,
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
    DuplicateAmmeterError,
    UnknownAmmeterError,
)
from .factory import AmmeterFactory, AmmeterRegistry
from .models import CurrentMeasurement
from .socket_transport import SocketTransport

__all__ = [
    "Ammeter",
    "AmmeterClientError",
    "AmmeterConnectionError",
    "AmmeterFactory",
    "AmmeterProtocolError",
    "AmmeterRegistry",
    "AmmeterTimeoutError",
    "CurrentMeasurement",
    "DuplicateAmmeterError",
    "MeasurementTransport",
    "SocketAmmeter",
    "SocketTransport",
    "UnknownAmmeterError",
]
