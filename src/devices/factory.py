from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone

from Ammeters.AcmeAmmeter import AcmeAmmeter
from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.base_ammeter import AmmeterEmulatorBase
from Ammeters.faults import FaultProfile
from src.utils.config import (
    AmmeterConfig,
    ApplicationConfig,
    ConfiguredAmmeter,
    ConfigurationError,
    UsbAmmeterConfig,
)

from .ammeter import CommandAmmeter, MonotonicClock, WallClock
from .contracts import Ammeter, MeasurementTransport
from .errors import DuplicateAmmeterError, UnknownAmmeterError
from .socket_transport import SocketTransport
from .usb_transport import EmulatedUsbBackend, UsbTransport


TransportBuilder = Callable[[ConfiguredAmmeter, float], MeasurementTransport]

_USB_EMULATOR_TYPES: dict[str, type[AmmeterEmulatorBase]] = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
    "acme": AcmeAmmeter,
}


class AmmeterRegistry:
    """Case-insensitive lookup of configured ammeter domain drivers."""

    def __init__(self, ammeters: Iterable[Ammeter] = ()) -> None:
        self._ammeters: dict[str, Ammeter] = {}
        for ammeter in ammeters:
            self.register(ammeter)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._ammeters)

    def register(self, ammeter: Ammeter) -> None:
        if not callable(getattr(ammeter, "read_current", None)):
            raise TypeError("ammeter must implement the Ammeter protocol")
        normalized_name = _normalize_name(getattr(ammeter, "name", None))
        if normalized_name in self._ammeters:
            raise DuplicateAmmeterError(
                f"Ammeter {normalized_name!r} is already registered"
            )
        self._ammeters[normalized_name] = ammeter

    def get(self, name: str) -> Ammeter:
        normalized_name = _normalize_name(name)
        try:
            return self._ammeters[normalized_name]
        except KeyError as exc:
            available = ", ".join(self.names) or "none"
            raise UnknownAmmeterError(
                f"Unknown ammeter {name!r}; available ammeters: {available}"
            ) from exc

    def __iter__(self) -> Iterator[Ammeter]:
        return iter(self._ammeters.values())

    def __len__(self) -> int:
        return len(self._ammeters)


class AmmeterFactory:
    """Construct domain drivers from validated application configuration."""

    def __init__(
        self,
        *,
        transport_builder: TransportBuilder | None = None,
        wall_clock: WallClock | None = None,
        monotonic_clock: MonotonicClock | None = None,
    ) -> None:
        self._uses_default_transport_builder = transport_builder is None
        self._transport_builder = (
            transport_builder
            if transport_builder is not None
            else _build_transport
        )
        self._wall_clock = (
            wall_clock
            if wall_clock is not None
            else lambda: datetime.now(timezone.utc)
        )
        self._monotonic_clock = (
            monotonic_clock if monotonic_clock is not None else time.monotonic
        )

    def create(
        self,
        settings: ConfiguredAmmeter,
        request_timeout_seconds: float,
        *,
        fault_profile: FaultProfile | None = None,
    ) -> Ammeter:
        if self._uses_default_transport_builder:
            transport = _build_transport(
                settings,
                request_timeout_seconds,
                fault_profile=fault_profile,
            )
        else:
            transport = self._transport_builder(
                settings,
                request_timeout_seconds,
            )
        return CommandAmmeter(
            name=settings.name,
            command=settings.command_bytes,
            transport=transport,
            wall_clock=self._wall_clock,
            monotonic_clock=self._monotonic_clock,
        )

    def create_registry(self, config: ApplicationConfig) -> AmmeterRegistry:
        timeout = config.communication.request_timeout_seconds
        return AmmeterRegistry(
            self.create(
                settings,
                timeout,
                fault_profile=(
                    None
                    if config.fault_injection is None
                    else config.fault_injection.profile_for(settings.name)
                ),
            )
            for settings in config.ammeters
        )


def _build_transport(
    settings: ConfiguredAmmeter,
    request_timeout_seconds: float,
    *,
    fault_profile: FaultProfile | None = None,
) -> MeasurementTransport:
    if isinstance(settings, AmmeterConfig):
        return SocketTransport(
            host=settings.host,
            port=settings.port,
            timeout_seconds=request_timeout_seconds,
        )
    if isinstance(settings, UsbAmmeterConfig):
        if settings.emulated:
            try:
                emulator_type = _USB_EMULATOR_TYPES[settings.name]
            except KeyError as exc:
                supported = ", ".join(sorted(_USB_EMULATOR_TYPES))
                raise ConfigurationError(
                    f"Unsupported emulated USB ammeter {settings.name!r}; "
                    f"supported values: {supported}"
                ) from exc
            measurement_source = emulator_type(
                port=0,
                command=settings.command_bytes,
            )
            backend = EmulatedUsbBackend(
                command=settings.command_bytes,
                measurement_provider=measurement_source.measure_current,
                fault_profile=fault_profile,
            )
            return UsbTransport(
                vendor_id=settings.vendor_id,
                product_id=settings.product_id,
                serial_number=settings.serial_number,
                interface_number=settings.interface_number,
                alternate_setting=settings.alternate_setting,
                read_endpoint_address=settings.read_endpoint_address,
                write_endpoint_address=settings.write_endpoint_address,
                max_frame_bytes=settings.max_response_bytes,
                timeout_seconds=request_timeout_seconds,
                backend=backend,
            )
        return UsbTransport(
            vendor_id=settings.vendor_id,
            product_id=settings.product_id,
            serial_number=settings.serial_number,
            interface_number=settings.interface_number,
            alternate_setting=settings.alternate_setting,
            read_endpoint_address=settings.read_endpoint_address,
            write_endpoint_address=settings.write_endpoint_address,
            max_frame_bytes=settings.max_response_bytes,
            timeout_seconds=request_timeout_seconds,
        )
    raise TypeError("Unsupported ammeter transport configuration")


def _normalize_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("ammeter name must be a non-empty string")
    return name.strip().lower()
