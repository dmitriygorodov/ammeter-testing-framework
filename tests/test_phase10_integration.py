"""Phase 10 loopback tests exercise every fault through the real client stack."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from collections.abc import Iterator

from Ammeters.base_ammeter import AmmeterEmulatorBase
from Ammeters.faults import FaultKind, FaultProfile, FaultRule
from src.devices.ammeter import SocketAmmeter
from src.devices.errors import AmmeterProtocolError, AmmeterTimeoutError
from src.devices.socket_transport import SocketTransport


HOST = "127.0.0.1"
COMMAND = b"MEASURE_FIXED"


class _FixedAmmeter(AmmeterEmulatorBase):
    DEFAULT_COMMAND = COMMAND

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.measure_calls = 0

    def measure_current(self) -> float:
        self.measure_calls += 1
        return 10.0


@contextmanager
def _running(emulator: AmmeterEmulatorBase) -> Iterator[None]:
    emulator.start(2.0)
    try:
        yield
    finally:
        emulator.stop(2.0)


def _client(emulator: AmmeterEmulatorBase, *, timeout: float = 0.5) -> SocketAmmeter:
    return SocketAmmeter(
        name="fixed",
        command=COMMAND,
        transport=SocketTransport(HOST, emulator.port, timeout),
    )


class FaultInjectionIntegrationTests(unittest.TestCase):
    def test_scheduled_protocol_faults_and_offset_trigger_exactly_once(self) -> None:
        rules = (
            FaultRule(
                request_number=1,
                kind=FaultKind.CURRENT_OFFSET,
                current_offset_a=2.5,
            ),
            FaultRule(
                request_number=2,
                kind=FaultKind.ERROR_RESPONSE,
                error_message="simulated sensor fault",
            ),
            FaultRule(
                request_number=3,
                kind=FaultKind.MALFORMED_RESPONSE,
                response_payload="nan",
            ),
            FaultRule(request_number=4, kind=FaultKind.DISCONNECT),
        )
        emulator = _FixedAmmeter(0, fault_profile=FaultProfile(rules))
        with _running(emulator):
            client = _client(emulator)
            self.assertEqual(client.read_current().current_a, 12.5)
            with self.assertRaisesRegex(AmmeterProtocolError, "simulated sensor"):
                client.read_current()
            with self.assertRaisesRegex(AmmeterProtocolError, "non-finite"):
                client.read_current()
            with self.assertRaisesRegex(AmmeterProtocolError, "closed"):
                client.read_current()
            self.assertEqual(client.read_current().current_a, 10.0)

            self.assertEqual(emulator.accepted_request_count, 5)
            self.assertEqual(emulator.triggered_faults, rules)
            self.assertEqual(emulator.measure_calls, 2)

    def test_response_delay_produces_typed_timeout_then_server_recovers(self) -> None:
        delay = FaultRule(
            request_number=1,
            kind=FaultKind.RESPONSE_DELAY,
            delay_seconds=0.2,
        )
        emulator = _FixedAmmeter(0, fault_profile=FaultProfile((delay,)))
        with _running(emulator):
            with self.assertRaises(AmmeterTimeoutError):
                _client(emulator, timeout=0.05).read_current()
            self.assertEqual(
                _client(emulator, timeout=0.75).read_current().current_a,
                10.0,
            )
            self.assertEqual(emulator.accepted_request_count, 2)
            self.assertEqual(emulator.triggered_faults, (delay,))

    def test_unknown_command_does_not_consume_measurement_fault_schedule(self) -> None:
        offset = FaultRule(
            request_number=1,
            kind=FaultKind.CURRENT_OFFSET,
            current_offset_a=-1.0,
        )
        emulator = _FixedAmmeter(0, fault_profile=FaultProfile((offset,)))
        with _running(emulator):
            transport = SocketTransport(HOST, emulator.port, 0.5)
            self.assertEqual(
                transport.request(b"UNKNOWN"),
                b"ERROR unknown command",
            )
            self.assertEqual(emulator.accepted_request_count, 0)
            self.assertEqual(_client(emulator).read_current().current_a, 9.0)
            self.assertEqual(emulator.accepted_request_count, 1)

    def test_restart_replays_the_same_deterministic_schedule(self) -> None:
        offset = FaultRule(
            request_number=1,
            kind=FaultKind.CURRENT_OFFSET,
            current_offset_a=1.0,
        )
        emulator = _FixedAmmeter(0, fault_profile=FaultProfile((offset,)))
        for _ in range(2):
            with _running(emulator):
                self.assertEqual(_client(emulator).read_current().current_a, 11.0)
                self.assertEqual(emulator.accepted_request_count, 1)
                self.assertEqual(emulator.triggered_faults, (offset,))

    def test_delay_is_interrupted_by_shutdown(self) -> None:
        delay = FaultRule(
            request_number=1,
            kind=FaultKind.RESPONSE_DELAY,
            delay_seconds=30.0,
        )
        emulator = _FixedAmmeter(0, fault_profile=FaultProfile((delay,)))
        emulator.start(2.0)
        transport = SocketTransport(HOST, emulator.port, 0.05)
        with self.assertRaises(AmmeterTimeoutError):
            transport.request(COMMAND)

        emulator.stop(0.5)

        self.assertIsNone(emulator.server_thread)


if __name__ == "__main__":
    unittest.main()
