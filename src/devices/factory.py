from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone

from src.utils.config import AmmeterConfig, ApplicationConfig

from .ammeter import MonotonicClock, SocketAmmeter, WallClock
from .contracts import Ammeter, MeasurementTransport
from .errors import DuplicateAmmeterError, UnknownAmmeterError
from .socket_transport import SocketTransport


TransportBuilder = Callable[[AmmeterConfig, float], MeasurementTransport]


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
        self._transport_builder = (
            transport_builder
            if transport_builder is not None
            else _build_socket_transport
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
        settings: AmmeterConfig,
        request_timeout_seconds: float,
    ) -> Ammeter:
        transport = self._transport_builder(settings, request_timeout_seconds)
        return SocketAmmeter(
            name=settings.name,
            command=settings.command_bytes,
            transport=transport,
            wall_clock=self._wall_clock,
            monotonic_clock=self._monotonic_clock,
        )

    def create_registry(self, config: ApplicationConfig) -> AmmeterRegistry:
        timeout = config.communication.request_timeout_seconds
        return AmmeterRegistry(
            self.create(settings, timeout) for settings in config.ammeters
        )


def _build_socket_transport(
    settings: AmmeterConfig,
    request_timeout_seconds: float,
) -> MeasurementTransport:
    return SocketTransport(
        host=settings.host,
        port=settings.port,
        timeout_seconds=request_timeout_seconds,
    )


def _normalize_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("ammeter name must be a non-empty string")
    return name.strip().lower()
