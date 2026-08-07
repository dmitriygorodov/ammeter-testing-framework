"""Phase 1 loopback tests for the supplied ammeter emulators.

The suite intentionally uses only :mod:`unittest` and the Python standard
library.  It can therefore be run with ``python -m unittest`` while remaining
fully compatible with pytest discovery.
"""

from __future__ import annotations

import math
import socket
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import ClassVar
from unittest.mock import patch

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.base_ammeter import AmmeterEmulatorBase, AmmeterServerStartupError
from Ammeters.client import (
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
    request_current_from_ammeter,
)


HOST = "127.0.0.1"
SOCKET_TIMEOUT_SECONDS = 0.5
LIFECYCLE_TIMEOUT_SECONDS = 2.0


class _ScriptedServer:
    """One-request TCP server used to test client parsing in isolation."""

    def __init__(self, response: bytes) -> None:
        self.response = response
        self.port = 0
        self.request = b""
        self.error: BaseException | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._serve_once,
            name="scripted-ammeter-server",
            daemon=False,
        )

    def __enter__(self) -> "_ScriptedServer":
        self._thread.start()
        if not self._ready.wait(LIFECYCLE_TIMEOUT_SECONDS):
            self.fail_if_needed()
            raise RuntimeError("scripted test server did not become ready")
        return self

    def __exit__(self, *_: object) -> None:
        self._thread.join(LIFECYCLE_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            raise RuntimeError("scripted test server did not stop")
        self.fail_if_needed()

    def fail_if_needed(self) -> None:
        if self.error is not None:
            raise RuntimeError("scripted test server failed") from self.error

    def _serve_once(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((HOST, 0))
                listener.listen(1)
                listener.settimeout(LIFECYCLE_TIMEOUT_SECONDS)
                self.port = listener.getsockname()[1]
                self._ready.set()

                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(SOCKET_TIMEOUT_SECONDS)
                    self.request = connection.recv(1024)
                    if self.response:
                        connection.sendall(self.response)
        except BaseException as exc:  # Propagate background-thread failures.
            self.error = exc
            self._ready.set()


@contextmanager
def _running_emulators(
    emulators: list[AmmeterEmulatorBase],
) -> Iterator[None]:
    """Run emulator-owned threads and guarantee bounded cleanup."""

    started: list[AmmeterEmulatorBase] = []
    try:
        for emulator in emulators:
            emulator.start(LIFECYCLE_TIMEOUT_SECONDS)
            started.append(emulator)
        yield
    finally:
        for emulator in reversed(started):
            emulator.stop(LIFECYCLE_TIMEOUT_SECONDS)
            thread = emulator.server_thread
            if thread is not None and thread.is_alive():
                raise RuntimeError(f"{thread.name} remained alive after shutdown")


class ClientTests(unittest.TestCase):
    def test_returns_float_and_uses_newline_framing(self) -> None:
        with _ScriptedServer(b"12.375\n") as server:
            result = request_current_from_ammeter(
                server.port,
                b"READ_CURRENT",
                host=HOST,
                timeout=SOCKET_TIMEOUT_SECONDS,
            )

        self.assertIsInstance(result, float)
        self.assertEqual(result, 12.375)
        self.assertEqual(server.request, b"READ_CURRENT\n")

    def test_empty_reply_raises_protocol_error(self) -> None:
        with _ScriptedServer(b"") as server:
            with self.assertRaises(AmmeterProtocolError):
                request_current_from_ammeter(
                    server.port,
                    b"READ_CURRENT",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

    def test_malformed_reply_raises_protocol_error(self) -> None:
        with _ScriptedServer(b"not-a-number\n") as server:
            with self.assertRaises(AmmeterProtocolError):
                request_current_from_ammeter(
                    server.port,
                    b"READ_CURRENT",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

    def test_non_finite_reply_raises_protocol_error(self) -> None:
        with _ScriptedServer(b"nan\n") as server:
            with self.assertRaises(AmmeterProtocolError):
                request_current_from_ammeter(
                    server.port,
                    b"READ_CURRENT",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

    def test_connection_failure_raises_typed_error(self) -> None:
        with patch(
            "src.devices.socket_transport.socket.create_connection",
            side_effect=OSError("connection unavailable"),
        ):
            with self.assertRaises(AmmeterConnectionError):
                request_current_from_ammeter(
                    5000,
                    b"READ_CURRENT",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

    def test_socket_timeout_raises_typed_error(self) -> None:
        with patch(
            "src.devices.socket_transport.socket.create_connection",
            side_effect=socket.timeout("timed out"),
        ):
            with self.assertRaises(AmmeterTimeoutError):
                request_current_from_ammeter(
                    5000,
                    b"READ_CURRENT",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

    def test_non_finite_timeout_is_rejected(self) -> None:
        for timeout in (math.nan, math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    request_current_from_ammeter(
                        5000,
                        b"READ_CURRENT",
                        host=HOST,
                        timeout=timeout,
                    )


class EmulatorIntegrationTests(unittest.TestCase):
    AMMETERS: ClassVar[
        tuple[tuple[type[AmmeterEmulatorBase], bytes], ...]
    ] = (
        (GreenleeAmmeter, b"MEASURE_GREENLEE -get_measurement"),
        (EntesAmmeter, b"MEASURE_ENTES -get_data"),
        (CircutorAmmeter, b"MEASURE_CIRCUTOR -get_measurement"),
    )

    def test_each_emulator_accepts_its_exact_command(self) -> None:
        for emulator_type, expected_command in self.AMMETERS:
            with self.subTest(ammeter=emulator_type.__name__):
                emulator = emulator_type(0)
                with _running_emulators([emulator]):
                    self.assertGreater(emulator.port, 0)
                    self.assertEqual(emulator.get_current_command, expected_command)
                    result = request_current_from_ammeter(
                        emulator.port,
                        expected_command,
                        host=HOST,
                        timeout=SOCKET_TIMEOUT_SECONDS,
                    )

                self.assertIsInstance(result, float)
                self.assertTrue(math.isfinite(result))
                self.assertGreaterEqual(result, 0.0)

    def test_readiness_and_graceful_idempotent_shutdown(self) -> None:
        emulator = GreenleeAmmeter(0)
        emulator.start(LIFECYCLE_TIMEOUT_SECONDS)
        thread = emulator.server_thread
        try:
            self.assertTrue(
                emulator.wait_until_ready(LIFECYCLE_TIMEOUT_SECONDS),
                "server never reported that it was ready",
            )
            self.assertGreater(emulator.port, 0, "port=0 was not resolved")
        finally:
            emulator.stop(LIFECYCLE_TIMEOUT_SECONDS)

        self.assertIsNotNone(thread)
        self.assertFalse(thread.is_alive(), "shutdown did not unblock accept()")
        emulator.stop(LIFECYCLE_TIMEOUT_SECONDS)  # Repeated shutdown must remain safe.

        with self.assertRaises(OSError):
            socket.create_connection(
                (HOST, emulator.port), timeout=SOCKET_TIMEOUT_SECONDS
            ).close()

    def test_unknown_command_does_not_stop_emulator(self) -> None:
        emulator = GreenleeAmmeter(0)
        with _running_emulators([emulator]):
            with self.assertRaises(AmmeterProtocolError):
                request_current_from_ammeter(
                    emulator.port,
                    b"NOT_A_REAL_COMMAND",
                    host=HOST,
                    timeout=SOCKET_TIMEOUT_SECONDS,
                )

            measurement = request_current_from_ammeter(
                emulator.port,
                emulator.get_current_command,
                host=HOST,
                timeout=SOCKET_TIMEOUT_SECONDS,
            )

        self.assertTrue(math.isfinite(measurement))

    def test_fragmented_request_is_reassembled(self) -> None:
        emulator = GreenleeAmmeter(0)
        with _running_emulators([emulator]):
            with socket.create_connection(
                (HOST, emulator.port), timeout=SOCKET_TIMEOUT_SECONDS
            ) as connection:
                connection.settimeout(SOCKET_TIMEOUT_SECONDS)
                connection.sendall(b"MEASURE_GREENLEE ")
                connection.sendall(b"-get_measure")
                connection.sendall(b"ment\n")
                response = bytearray()
                while not response.endswith(b"\n"):
                    chunk = connection.recv(256)
                    self.assertTrue(chunk, "server closed before completing its frame")
                    response.extend(chunk)

        self.assertTrue(response.endswith(b"\n"))
        self.assertTrue(math.isfinite(float(bytes(response).rstrip(b"\n"))))

    def test_bind_failure_is_exposed_through_startup_error(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied_listener:
            occupied_listener.bind((HOST, 0))
            occupied_listener.listen(1)
            occupied_port = occupied_listener.getsockname()[1]
            emulator = GreenleeAmmeter(occupied_port)
            with self.assertRaises(AmmeterServerStartupError):
                emulator.start(LIFECYCLE_TIMEOUT_SECONDS)

        self.assertIsInstance(emulator.startup_error, OSError)

    def test_second_live_listener_on_same_port_is_rejected(self) -> None:
        first = GreenleeAmmeter(0)
        first.start(LIFECYCLE_TIMEOUT_SECONDS)
        second = GreenleeAmmeter(first.port)
        try:
            with self.assertRaises(AmmeterServerStartupError):
                second.start(LIFECYCLE_TIMEOUT_SECONDS)
            self.assertIsInstance(second.startup_error, OSError)
        finally:
            second.stop(LIFECYCLE_TIMEOUT_SECONDS)
            first.stop(LIFECYCLE_TIMEOUT_SECONDS)

    def test_stop_requested_before_worker_runs_is_not_lost(self) -> None:
        emulator = GreenleeAmmeter(0)
        emulator.stop_server()
        thread = threading.Thread(
            target=emulator.start_server,
            name="early-stop-regression-test",
            daemon=False,
        )
        thread.start()
        thread.join(LIFECYCLE_TIMEOUT_SECONDS)

        self.assertFalse(thread.is_alive())
        self.assertFalse(emulator.is_running)
        self.assertEqual(emulator.port, 0, "stopped worker unexpectedly bound a port")

        # The owned lifecycle deliberately starts a new generation and must still work.
        emulator.start(LIFECYCLE_TIMEOUT_SECONDS)
        emulator.stop(LIFECYCLE_TIMEOUT_SECONDS)

    def test_all_emulators_start_together_and_restart_on_same_ports(self) -> None:
        emulators = [emulator_type(0) for emulator_type, _ in self.AMMETERS]

        for cycle in range(2):
            with self.subTest(cycle=cycle + 1):
                with _running_emulators(emulators):
                    ports = [emulator.port for emulator in emulators]
                    self.assertEqual(len(ports), len(set(ports)))
                    self.assertTrue(all(port > 0 for port in ports))

                    for emulator, (_, command) in zip(emulators, self.AMMETERS):
                        measurement = request_current_from_ammeter(
                            emulator.port,
                            command,
                            host=HOST,
                            timeout=SOCKET_TIMEOUT_SECONDS,
                        )
                        self.assertIsInstance(measurement, float)
                        self.assertTrue(math.isfinite(measurement))

                for emulator in emulators:
                    thread = emulator.server_thread
                    self.assertTrue(thread is None or not thread.is_alive())


if __name__ == "__main__":
    unittest.main()
