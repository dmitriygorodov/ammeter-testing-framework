"""Unified ammeter device and transport abstractions."""

from .ammeter import CommandAmmeter, SocketAmmeter
from .contracts import Ammeter, MeasurementTransport
from .errors import (
    AmmeterClientError,
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
    AmmeterTransportDependencyError,
    DuplicateAmmeterError,
    UnknownAmmeterError,
)
from .factory import AmmeterFactory, AmmeterRegistry
from .models import CurrentMeasurement
from .socket_transport import SocketTransport
from .usb_transport import EmulatedUsbBackend, PyUsbBackend, UsbBackend, UsbTransport

__all__ = [
    "Ammeter",
    "AmmeterClientError",
    "AmmeterConnectionError",
    "CommandAmmeter",
    "AmmeterFactory",
    "AmmeterProtocolError",
    "AmmeterRegistry",
    "AmmeterTimeoutError",
    "AmmeterTransportDependencyError",
    "CurrentMeasurement",
    "DuplicateAmmeterError",
    "EmulatedUsbBackend",
    "MeasurementTransport",
    "SocketAmmeter",
    "SocketTransport",
    "PyUsbBackend",
    "UsbBackend",
    "UsbTransport",
    "UnknownAmmeterError",
]
