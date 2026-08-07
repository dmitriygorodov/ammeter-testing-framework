"""Deterministic checks for operating-system-specific portability branches."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from Ammeters.base_ammeter import AmmeterEmulatorBase


class _RecordingSocket:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.calls.append((level, option, value))


class BindSemanticsPortabilityTests(unittest.TestCase):
    def test_windows_uses_exclusive_address_binding(self) -> None:
        server_socket = _RecordingSocket()
        exclusive_option = 0x4
        with (
            patch("Ammeters.base_ammeter.os.name", "nt"),
            patch.object(
                socket,
                "SO_EXCLUSIVEADDRUSE",
                exclusive_option,
                create=True,
            ),
        ):
            AmmeterEmulatorBase._configure_bind_semantics(  # type: ignore[arg-type]
                server_socket
            )

        self.assertEqual(
            server_socket.calls,
            [(socket.SOL_SOCKET, exclusive_option, 1)],
        )

    def test_posix_uses_reusable_address_binding(self) -> None:
        server_socket = _RecordingSocket()
        with patch("Ammeters.base_ammeter.os.name", "posix"):
            AmmeterEmulatorBase._configure_bind_semantics(  # type: ignore[arg-type]
                server_socket
            )

        self.assertEqual(
            server_socket.calls,
            [(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)],
        )


if __name__ == "__main__":
    unittest.main()
