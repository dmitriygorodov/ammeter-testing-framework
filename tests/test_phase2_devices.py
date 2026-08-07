"""Hardware-free unit tests for ammeter adapters, registries, and factories."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from src.devices.ammeter import SocketAmmeter
from src.devices.errors import (
    AmmeterProtocolError,
    DuplicateAmmeterError,
    UnknownAmmeterError,
)
from src.devices.factory import AmmeterFactory, AmmeterRegistry
from src.devices.models import CurrentMeasurement
from src.utils.config import AmmeterConfig, ApplicationConfig, CommunicationConfig


class _FakeTransport:
    def __init__(self, response: bytes = b"1.0\n") -> None:
        self.response = response
        self.commands: list[bytes] = []
        self.error: BaseException | None = None

    def request(self, command: bytes) -> bytes:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.response


class _SequenceClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class _FalseyCallable:
    """Callable test double that is valid even though bool(instance) is false."""

    def __init__(self, callback: Callable[..., Any]) -> None:
        self._callback = callback

    def __bool__(self) -> bool:
        return False

    def __call__(self, *args: object) -> Any:
        return self._callback(*args)


class _FakeAmmeter:
    def __init__(
        self,
        name: str,
        *,
        current_a: float = 1.0,
        error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.current_a = current_a
        self.error = error
        self.calls = 0

    def read_current(self) -> CurrentMeasurement:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CurrentMeasurement(
            ammeter_name=self.name.strip().lower(),
            current_a=self.current_a,
            measured_at_utc=datetime(2026, 8, 6, tzinfo=timezone.utc),
            monotonic_time_s=float(self.calls),
            latency_seconds=0.0,
        )


class SocketAmmeterTests(unittest.TestCase):
    def test_transport_must_implement_request_contract(self) -> None:
        with self.assertRaisesRegex(TypeError, "transport"):
            SocketAmmeter("greenlee", b"READ_CURRENT", object())  # type: ignore[arg-type]

    def test_falsey_injected_clocks_are_honored(self) -> None:
        measured_at = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
        ammeter = SocketAmmeter(
            "greenlee",
            b"READ_CURRENT",
            _FakeTransport(b"2.5"),
            wall_clock=_FalseyCallable(lambda: measured_at),
            monotonic_clock=_FalseyCallable(_SequenceClock(8.0, 8.25)),
        )

        result = ammeter.read_current()

        self.assertIs(result.measured_at_utc, measured_at)
        self.assertEqual(result.monotonic_time_s, 8.25)
        self.assertEqual(result.latency_seconds, 0.25)

    def test_measurement_uses_transport_and_records_completion_timing(self) -> None:
        transport = _FakeTransport(b" 12.375 ")
        measured_at = datetime(2026, 8, 6, 13, 0, tzinfo=timezone.utc)
        ammeter = SocketAmmeter(
            "greenlee",
            b"READ_CURRENT",
            transport,
            wall_clock=lambda: measured_at,
            monotonic_clock=_SequenceClock(100.0, 100.125),
        )

        result = ammeter.read_current()

        self.assertEqual(transport.commands, [b"READ_CURRENT"])
        self.assertEqual(result.ammeter_name, "greenlee")
        self.assertEqual(result.current_a, 12.375)
        self.assertIs(result.measured_at_utc, measured_at)
        self.assertEqual(result.monotonic_time_s, 100.125)
        self.assertAlmostEqual(result.latency_seconds, 0.125)

    def test_adapter_rejects_empty_malformed_and_non_finite_responses(self) -> None:
        for response in (
            b"",
            b"not-a-number",
            b"nan",
            b"inf",
            b"1.0\n",
            b"\xff",
            b"ERROR simulated failure",
        ):
            with self.subTest(response=response):
                ammeter = SocketAmmeter(
                    "greenlee",
                    b"READ_CURRENT",
                    _FakeTransport(response),
                    wall_clock=lambda: datetime.now(timezone.utc),
                    monotonic_clock=_SequenceClock(1.0, 1.1),
                )
                with self.assertRaises(AmmeterProtocolError):
                    ammeter.read_current()

    def test_transport_errors_propagate_without_being_hidden(self) -> None:
        failure = TimeoutError("instrument did not answer")
        transport = _FakeTransport()
        transport.error = failure
        ammeter = SocketAmmeter(
            "greenlee",
            b"READ_CURRENT",
            transport,
            monotonic_clock=_SequenceClock(1.0),
        )

        with self.assertRaises(TimeoutError) as raised:
            ammeter.read_current()

        self.assertIs(raised.exception, failure)


class AmmeterRegistryTests(unittest.TestCase):
    def test_lookup_normalizes_case_and_surrounding_whitespace(self) -> None:
        greenlee = _FakeAmmeter("Greenlee")
        entes = _FakeAmmeter("entes")
        registry = AmmeterRegistry([greenlee, entes])

        self.assertIs(registry.get("  GREENLEE "), greenlee)
        self.assertIs(registry.get("Entes"), entes)
        self.assertEqual(registry.names, ("greenlee", "entes"))
        self.assertEqual(len(registry), 2)
        self.assertEqual(list(registry), [greenlee, entes])

    def test_duplicate_normalized_name_is_rejected(self) -> None:
        registry = AmmeterRegistry([_FakeAmmeter("greenlee")])

        with self.assertRaisesRegex(
            DuplicateAmmeterError, "greenlee|duplicate|registered"
        ):
            registry.register(_FakeAmmeter("  GREENLEE "))

    def test_unknown_name_raises_typed_error_with_available_names(self) -> None:
        registry = AmmeterRegistry([_FakeAmmeter("greenlee"), _FakeAmmeter("entes")])

        with self.assertRaises(UnknownAmmeterError) as raised:
            registry.get("missing")

        message = str(raised.exception).lower()
        self.assertIn("missing", message)
        self.assertIn("greenlee", message)
        self.assertIn("entes", message)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "name"):
            AmmeterRegistry([_FakeAmmeter("  ")])

    def test_registered_device_must_implement_read_contract(self) -> None:
        class _NotAnAmmeter:
            name = "greenlee"

        with self.assertRaisesRegex(TypeError, "Ammeter|read_current|protocol"):
            AmmeterRegistry([_NotAnAmmeter()])  # type: ignore[list-item]


class AmmeterFactoryTests(unittest.TestCase):
    FIXED_TIME = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)

    def test_create_uses_configured_endpoint_timeout_and_injected_clocks(self) -> None:
        transports: list[_FakeTransport] = []
        builder_calls: list[tuple[AmmeterConfig, float]] = []

        def build_transport(
            settings: AmmeterConfig, timeout_seconds: float
        ) -> _FakeTransport:
            builder_calls.append((settings, timeout_seconds))
            transport = _FakeTransport(b"3.5")
            transports.append(transport)
            return transport

        factory = AmmeterFactory(
            transport_builder=build_transport,
            wall_clock=lambda: self.FIXED_TIME,
            monotonic_clock=_SequenceClock(10.0, 10.25),
        )
        settings = AmmeterConfig(
            name="greenlee",
            host="192.0.2.10",
            port=4321,
            command="MEASURE",
        )

        ammeter = factory.create(settings, request_timeout_seconds=0.75)
        measurement = ammeter.read_current()

        self.assertEqual(builder_calls, [(settings, 0.75)])
        self.assertEqual(transports[0].commands, [b"MEASURE"])
        self.assertEqual(measurement.current_a, 3.5)
        self.assertEqual(measurement.measured_at_utc, self.FIXED_TIME)
        self.assertEqual(measurement.monotonic_time_s, 10.25)
        self.assertEqual(measurement.latency_seconds, 0.25)

    def test_falsey_injected_builder_and_clocks_are_honored(self) -> None:
        measured_at = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
        transport = _FakeTransport(b"4.25")
        builder_calls: list[tuple[AmmeterConfig, float]] = []

        def build_transport(
            settings: AmmeterConfig, timeout_seconds: float
        ) -> _FakeTransport:
            builder_calls.append((settings, timeout_seconds))
            return transport

        settings = AmmeterConfig(
            name="greenlee",
            host="127.0.0.1",
            port=5000,
            command="MEASURE",
        )
        factory = AmmeterFactory(
            transport_builder=_FalseyCallable(build_transport),
            wall_clock=_FalseyCallable(lambda: measured_at),
            monotonic_clock=_FalseyCallable(_SequenceClock(3.0, 3.1)),
        )

        measurement = factory.create(settings, 0.5).read_current()

        self.assertEqual(builder_calls, [(settings, 0.5)])
        self.assertIs(measurement.measured_at_utc, measured_at)
        self.assertEqual(measurement.current_a, 4.25)
        self.assertAlmostEqual(measurement.latency_seconds, 0.1)

    def test_create_registry_preserves_application_config_order(self) -> None:
        responses = iter((b"1.0", b"2.0"))
        created: list[_FakeTransport] = []

        builder_calls: list[tuple[AmmeterConfig, float]] = []

        def build_transport(
            settings: AmmeterConfig, timeout_seconds: float
        ) -> _FakeTransport:
            builder_calls.append((settings, timeout_seconds))
            transport = _FakeTransport(next(responses))
            created.append(transport)
            return transport

        config = ApplicationConfig(
            ammeters=(
                AmmeterConfig("greenlee", "127.0.0.1", 5000, "READ_GREENLEE"),
                AmmeterConfig("entes", "127.0.0.1", 5001, "READ_ENTES"),
            ),
            communication=CommunicationConfig(
                request_timeout_seconds=1.25,
                server_startup_timeout_seconds=2.0,
                server_shutdown_timeout_seconds=2.0,
            ),
        )
        factory = AmmeterFactory(
            transport_builder=build_transport,
            wall_clock=lambda: self.FIXED_TIME,
            monotonic_clock=_SequenceClock(1.0, 1.1, 2.0, 2.2),
        )

        registry = factory.create_registry(config)

        self.assertEqual(registry.names, ("greenlee", "entes"))
        self.assertEqual(registry.get("greenlee").read_current().current_a, 1.0)
        self.assertEqual(registry.get("entes").read_current().current_a, 2.0)
        self.assertEqual(created[0].commands, [b"READ_GREENLEE"])
        self.assertEqual(created[1].commands, [b"READ_ENTES"])
        self.assertEqual(
            builder_calls,
            [(config.ammeters[0], 1.25), (config.ammeters[1], 1.25)],
        )


if __name__ == "__main__":
    unittest.main()
