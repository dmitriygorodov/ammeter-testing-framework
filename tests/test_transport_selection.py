"""TCP/USB transport selection and hardware-free USB contract tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from Ammeters.faults import FaultKind, FaultProfile, FaultRule
from examples import run_analysis_test, run_archive_test, run_sampling_test
from main import _build_emulators
from src.devices.ammeter import CommandAmmeter, SocketAmmeter
from src.devices.errors import (
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
    AmmeterTransportDependencyError,
)
from src.devices.factory import AmmeterFactory
from src.devices.usb_transport import EmulatedUsbBackend, PyUsbBackend, UsbTransport
from src.utils.config import (
    AmmeterConfig,
    ApplicationConfig,
    CommunicationConfig,
    ConfigurationError,
    TransportKind,
    UsbAmmeterConfig,
    load_application_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeUsbBackend:
    def __init__(self, response: bytes = b"2.75\n") -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []
        self.error: BaseException | None = None

    def exchange(self, **arguments: object) -> bytes:
        self.calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.response


class UsbTransportTests(unittest.TestCase):
    def test_request_frames_command_and_returns_unframed_payload(self) -> None:
        backend = _FakeUsbBackend()
        transport = UsbTransport(
            vendor_id=0x1234,
            product_id=0x5678,
            serial_number="ATE-USB-001",
            interface_number=2,
            alternate_setting=1,
            read_endpoint_address=0x81,
            write_endpoint_address=0x02,
            max_frame_bytes=128,
            timeout_seconds=0.25,
            backend=backend,
        )

        response = transport.request(b"READ_CURRENT")

        self.assertEqual(response, b"2.75")
        self.assertEqual(len(backend.calls), 1)
        call = backend.calls[0]
        self.assertEqual(call["request_payload"], b"READ_CURRENT\n")
        self.assertEqual(call["timeout_ms"], 250)
        self.assertEqual(call["max_response_bytes"], 129)
        self.assertEqual(call["read_endpoint_address"], 0x81)
        self.assertEqual(call["write_endpoint_address"], 0x02)

    def test_protocol_rejects_missing_or_trailing_frame_data(self) -> None:
        invalid_responses = (
            b"2.75",
            b"2.75\ntrailing",
            b"2.75\r\n",
            b"x" * 9 + b"\n",
            bytearray(b"2.75\n"),
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                transport = UsbTransport(
                    vendor_id=1,
                    product_id=2,
                    timeout_seconds=1.0,
                    max_frame_bytes=8,
                    backend=_FakeUsbBackend(response),  # type: ignore[arg-type]
                )
                with self.assertRaises(AmmeterProtocolError):
                    transport.request(b"READ")

    def test_backend_timeout_and_connection_failures_are_typed(self) -> None:
        failures = (
            (TimeoutError("late"), AmmeterTimeoutError),
            (OSError("disconnected"), AmmeterConnectionError),
        )
        for failure, expected_type in failures:
            with self.subTest(failure=failure):
                backend = _FakeUsbBackend()
                backend.error = failure
                transport = UsbTransport(
                    vendor_id=1,
                    product_id=2,
                    timeout_seconds=1.0,
                    backend=backend,
                )
                with self.assertRaises(expected_type) as raised:
                    transport.request(b"READ")
                self.assertIs(raised.exception.__cause__, failure)

    def test_configuration_and_command_boundaries_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "IN endpoint"):
            UsbTransport(
                vendor_id=1,
                product_id=2,
                read_endpoint_address=0x01,
                timeout_seconds=1.0,
            )
        with self.assertRaisesRegex(ValueError, "OUT endpoint"):
            UsbTransport(
                vendor_id=1,
                product_id=2,
                write_endpoint_address=0x81,
                timeout_seconds=1.0,
            )
        transport = UsbTransport(
            vendor_id=1,
            product_id=2,
            timeout_seconds=1.0,
            backend=_FakeUsbBackend(),
        )
        for command in (b"", b"READ\n", b"READ\r"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    transport.request(command)

    def test_pyusb_is_optional_until_usb_exchange_is_requested(self) -> None:
        transport = UsbTransport(
            vendor_id=1,
            product_id=2,
            timeout_seconds=1.0,
        )
        self.assertIsInstance(transport.backend, PyUsbBackend)

        with patch.dict(
            sys.modules,
            {"usb": None, "usb.core": None, "usb.util": None},
        ):
            with self.assertRaises(AmmeterTransportDependencyError):
                transport.request(b"READ")

    def test_pyusb_backend_discovers_endpoints_exchanges_and_releases(self) -> None:
        class _Endpoint:
            def __init__(self, address: int, response: bytes = b"") -> None:
                self.bEndpointAddress = address
                self.response = response
                self.writes: list[tuple[bytes, int]] = []

            def write(self, payload: bytes, *, timeout: int) -> None:
                self.writes.append((payload, timeout))

            def read(self, size: int, *, timeout: int) -> bytes:
                self.read_call = (size, timeout)
                return self.response

        output_endpoint = _Endpoint(0x02)
        input_endpoint = _Endpoint(0x81, b"4.5\n")
        interface = (output_endpoint, input_endpoint)

        class _Configuration:
            def __getitem__(self, key: tuple[int, int]):
                self.requested_interface = key
                return interface

        configuration = _Configuration()

        class _Device:
            iSerialNumber = 1

            def set_configuration(self) -> None:
                self.configured = True

            def get_active_configuration(self) -> _Configuration:
                return configuration

        device = _Device()
        disposed: list[object] = []
        usb_package = ModuleType("usb")
        usb_package.__path__ = []  # type: ignore[attr-defined]
        core_module = ModuleType("usb.core")
        util_module = ModuleType("usb.util")
        core_module.find = lambda **_: (device,)  # type: ignore[attr-defined]
        core_module.USBError = OSError  # type: ignore[attr-defined]
        core_module.USBTimeoutError = TimeoutError  # type: ignore[attr-defined]
        util_module.ENDPOINT_IN = 0x80  # type: ignore[attr-defined]
        util_module.ENDPOINT_OUT = 0x00  # type: ignore[attr-defined]
        util_module.endpoint_direction = lambda address: address & 0x80  # type: ignore[attr-defined]
        util_module.find_descriptor = (  # type: ignore[attr-defined]
            lambda values, custom_match: next(
                (value for value in values if custom_match(value)),
                None,
            )
        )
        util_module.get_string = lambda *_: "ATE-USB-001"  # type: ignore[attr-defined]
        util_module.dispose_resources = disposed.append  # type: ignore[attr-defined]
        usb_package.core = core_module  # type: ignore[attr-defined]
        usb_package.util = util_module  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "usb": usb_package,
                "usb.core": core_module,
                "usb.util": util_module,
            },
        ):
            response = PyUsbBackend().exchange(
                vendor_id=0x1234,
                product_id=0x5678,
                serial_number="ATE-USB-001",
                interface_number=2,
                alternate_setting=1,
                read_endpoint_address=None,
                write_endpoint_address=None,
                request_payload=b"READ\n",
                max_response_bytes=129,
                timeout_ms=250,
            )

        self.assertEqual(response, b"4.5\n")
        self.assertEqual(output_endpoint.writes, [(b"READ\n", 250)])
        self.assertEqual(input_endpoint.read_call, (129, 250))
        self.assertEqual(configuration.requested_interface, (2, 1))
        self.assertEqual(disposed, [device])

    def test_emulated_backend_uses_same_framing_and_fault_contract(self) -> None:
        backend = EmulatedUsbBackend(
            command=b"READ_CURRENT",
            measurement_provider=lambda: 2.5,
            fault_profile=FaultProfile(
                (
                    FaultRule(
                        request_number=1,
                        kind=FaultKind.CURRENT_OFFSET,
                        current_offset_a=0.75,
                    ),
                    FaultRule(
                        request_number=2,
                        kind=FaultKind.ERROR_RESPONSE,
                        error_message="simulated overload",
                    ),
                )
            ),
        )
        transport = UsbTransport(
            vendor_id=1,
            product_id=2,
            timeout_seconds=1.0,
            backend=backend,
        )

        self.assertEqual(transport.request(b"READ_CURRENT"), b"3.25")
        with self.assertRaisesRegex(AmmeterProtocolError, "simulated overload"):
            CommandAmmeter(
                name="acme",
                command=b"READ_CURRENT",
                transport=transport,
            ).read_current()
        self.assertEqual(backend.accepted_request_count, 2)
        self.assertEqual(len(backend.triggered_faults), 2)


class TransportConfigurationTests(unittest.TestCase):
    def _load(self, document: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(document, encoding="utf-8")
            return load_application_config(path)

    def test_legacy_tcp_and_explicit_usb_can_share_one_registry(self) -> None:
        config = self._load(
            """
ammeters:
  greenlee:
    host: 127.0.0.1
    port: 5000
    command: MEASURE_GREENLEE
  entes:
    transport: usb
    vendor_id: 0x1234
    product_id: 0x5678
    serial_number: ATE-USB-001
    interface_number: 2
    alternate_setting: 1
    read_endpoint_address: 0x81
    write_endpoint_address: 0x02
    max_response_bytes: 2048
    command: READ_CURRENT
"""
        )

        tcp, usb = config.ammeters
        self.assertIsInstance(tcp, AmmeterConfig)
        self.assertIs(tcp.transport_kind, TransportKind.TCP)
        self.assertTrue(tcp.emulated)
        self.assertIsInstance(usb, UsbAmmeterConfig)
        self.assertIs(usb.transport_kind, TransportKind.USB)
        self.assertFalse(usb.emulated)
        self.assertEqual(usb.vendor_id, 0x1234)
        self.assertEqual(usb.read_endpoint_address, 0x81)
        self.assertEqual(usb.max_response_bytes, 2048)

    def test_checked_in_usb_bench_example_is_valid_hardware_config(self) -> None:
        config = load_application_config(
            PROJECT_ROOT / "config" / "usb-bench.example.yaml"
        )

        self.assertEqual(len(config.ammeters), 1)
        settings = config.ammeters[0]
        self.assertIsInstance(settings, UsbAmmeterConfig)
        self.assertFalse(settings.emulated)
        self.assertIs(settings.transport_kind, TransportKind.USB)

    def test_invalid_or_ambiguous_usb_configuration_is_rejected(self) -> None:
        invalid_documents = (
            """
ammeters:
  meter:
    transport: serial
    command: READ
""",
            """
ammeters:
  meter:
    transport: usb
    product_id: 2
    command: READ
""",
            """
ammeters:
  meter:
    transport: usb
    vendor_id: 1
    product_id: 2
    read_endpoint_address: 0x01
    command: READ
""",
            """
ammeters:
  meter:
    transport: usb
    vendor_id: 1
    product_id: 2
    emulated: invalid
    command: READ
""",
            """
ammeters:
  first:
    transport: usb
    vendor_id: 1
    product_id: 2
    command: FIRST
  second:
    transport: usb
    vendor_id: 1
    product_id: 2
    command: SECOND
""",
        )
        for document in invalid_documents:
            with self.subTest(document=document):
                with self.assertRaises(ConfigurationError) as raised:
                    self._load(document)
                self.assertNotIsInstance(raised.exception, KeyError)

    def test_usb_emulation_is_valid_and_does_not_require_pyusb(self) -> None:
        config = self._load(
            """
ammeters:
  acme:
    transport: usb
    emulated: true
    vendor_id: 0x1234
    product_id: 0x5678
    serial_number: ACM-USB-001
    command: READ_CURRENT
"""
        )
        settings = config.ammeters[0]

        self.assertIsInstance(settings, UsbAmmeterConfig)
        self.assertTrue(settings.emulated)
        with patch("src.devices.usb_transport.PyUsbBackend") as pyusb_backend:
            measurement = AmmeterFactory().create_registry(config).get(
                "acme"
            ).read_current()
        pyusb_backend.assert_not_called()
        self.assertEqual(measurement.ammeter_name, "acme")
        self.assertGreaterEqual(measurement.current_a, 0.0)
        self.assertLessEqual(measurement.current_a, 10.0)

    def test_fault_injection_cannot_target_hardware_transport(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "locally emulated"):
            self._load(
                """
ammeters:
  meter:
    transport: usb
    vendor_id: 1
    product_id: 2
    command: READ
emulation:
  fault_injection:
    enabled: true
    ammeters:
      meter:
        - {request_number: 1, type: disconnect}
"""
            )

    def test_fault_profile_is_applied_to_emulated_usb(self) -> None:
        config = self._load(
            """
ammeters:
  acme:
    transport: usb
    emulated: true
    vendor_id: 1
    product_id: 2
    command: READ_CURRENT
emulation:
  fault_injection:
    enabled: true
    ammeters:
      acme:
        - request_number: 1
          type: error_response
          error_message: simulated USB fault
"""
        )

        with self.assertRaisesRegex(AmmeterProtocolError, "simulated USB fault"):
            AmmeterFactory().create_registry(config).get("acme").read_current()


class TransportFactoryTests(unittest.TestCase):
    def test_usb_settings_select_usb_transport_and_generic_adapter(self) -> None:
        settings = UsbAmmeterConfig(
            name="entes",
            vendor_id=0x1234,
            product_id=0x5678,
            command="READ_CURRENT",
            serial_number="ATE-USB-001",
            read_endpoint_address=0x81,
            write_endpoint_address=0x02,
            max_response_bytes=256,
        )
        fake_transport = _FakeUsbBackend(b"3.25\n")
        usb_transport = UsbTransport(
            vendor_id=settings.vendor_id,
            product_id=settings.product_id,
            serial_number=settings.serial_number,
            read_endpoint_address=settings.read_endpoint_address,
            write_endpoint_address=settings.write_endpoint_address,
            max_frame_bytes=settings.max_response_bytes,
            timeout_seconds=0.5,
            backend=fake_transport,
        )
        measured_at = datetime(2026, 8, 17, tzinfo=timezone.utc)

        with patch(
            "src.devices.factory.UsbTransport",
            return_value=usb_transport,
        ) as constructor:
            ammeter = AmmeterFactory(
                wall_clock=lambda: measured_at,
                monotonic_clock=iter((1.0, 1.1)).__next__,
            ).create(settings, 0.5)
            measurement = ammeter.read_current()

        self.assertIsInstance(ammeter, CommandAmmeter)
        self.assertIs(CommandAmmeter, SocketAmmeter)
        self.assertEqual(measurement.current_a, 3.25)
        constructor.assert_called_once_with(
            vendor_id=settings.vendor_id,
            product_id=settings.product_id,
            serial_number=settings.serial_number,
            interface_number=settings.interface_number,
            alternate_setting=settings.alternate_setting,
            read_endpoint_address=settings.read_endpoint_address,
            write_endpoint_address=settings.write_endpoint_address,
            max_frame_bytes=settings.max_response_bytes,
            timeout_seconds=0.5,
        )

    def test_emulator_lifecycle_skips_real_tcp_and_usb_hardware(self) -> None:
        config = ApplicationConfig(
            ammeters=(
                AmmeterConfig(
                    "greenlee",
                    "127.0.0.1",
                    5000,
                    "MEASURE_GREENLEE -get_measurement",
                    emulated=True,
                ),
                AmmeterConfig(
                    "entes",
                    "192.0.2.20",
                    5001,
                    "READ_ENTES",
                    emulated=False,
                ),
                UsbAmmeterConfig(
                    name="circutor",
                    vendor_id=1,
                    product_id=2,
                    command="READ_CIRCUTOR",
                    emulated=True,
                ),
            ),
            communication=CommunicationConfig(
                request_timeout_seconds=1.0,
                server_startup_timeout_seconds=2.0,
                server_shutdown_timeout_seconds=2.0,
            ),
        )

        configured_emulators = _build_emulators(config)

        self.assertEqual(
            [settings.name for settings, _ in configured_emulators],
            ["greenlee"],
        )


class TransportExampleCliTests(unittest.TestCase):
    def test_sampling_and_analysis_accept_hardware_config_and_ammeter(self) -> None:
        commands = (
            (run_sampling_test, "run_sampling_demo"),
            (run_analysis_test, "run_analysis_demo"),
        )
        for module, helper_name in commands:
            with self.subTest(module=module.__name__):
                with (
                    patch.object(
                        sys,
                        "argv",
                        [
                            module.__name__,
                            "--config",
                            "usb.yaml",
                            "--ammeter",
                            "entes",
                        ],
                    ),
                    patch.object(module, helper_name, return_value={}) as helper,
                ):
                    module.main()
                helper.assert_called_once_with(
                    "usb.yaml",
                    ammeter_name="entes",
                )

    def test_archive_accepts_hardware_config_ammeter_and_group(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_archive_test",
                    "--config",
                    "usb.yaml",
                    "--ammeter",
                    "circutor",
                    "--comparison-group",
                    "usb-calibration-a",
                ],
            ),
            patch.object(
                run_archive_test,
                "run_archive_demo",
                return_value={},
            ) as helper,
        ):
            exit_code = run_archive_test.main()

        self.assertEqual(exit_code, 0)
        helper.assert_called_once()
        positional, keywords = helper.call_args
        self.assertEqual(positional, ("usb.yaml",))
        self.assertEqual(keywords["ammeter_name"], "circutor")
        self.assertEqual(
            dict(keywords["metadata"].attributes)["comparison_group"],
            "usb-calibration-a",
        )


if __name__ == "__main__":
    unittest.main()
