from __future__ import annotations

import logging
import math
import os
import socket
import threading
from abc import ABC, abstractmethod

from Ammeters.faults import FaultKind, FaultProfile, FaultRule


LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
MAX_FRAME_BYTES = 1_024
ACCEPT_POLL_SECONDS = 0.1
CLIENT_IO_TIMEOUT_SECONDS = 0.5
DEFAULT_LIFECYCLE_TIMEOUT_SECONDS = 2.0


class AmmeterServerError(RuntimeError):
    """Base class for emulator server lifecycle failures."""


class AmmeterServerStartupError(AmmeterServerError):
    """The emulator server did not bind and become ready."""


class AmmeterServerShutdownError(AmmeterServerError):
    """The emulator server thread did not stop within its deadline."""


class AmmeterEmulatorBase(ABC):
    """TCP server used by the supplied ammeter emulators.

    ``start`` and ``stop`` own the worker-thread lifecycle and are the normal
    public API. ``start_server`` remains as the blocking server loop for
    compatibility with the supplied starter, but lifecycle-safe callers should
    not create their own thread around it.
    """

    DEFAULT_COMMAND: bytes | None = None

    def __init__(
        self,
        port: int,
        host: str = DEFAULT_HOST,
        command: bytes | None = None,
        *,
        fault_profile: FaultProfile | None = None,
    ) -> None:
        if isinstance(port, bool) or not isinstance(port, int):
            raise TypeError("port must be an integer")
        if not 0 <= port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host must be a non-empty string")

        effective_command = command if command is not None else self.DEFAULT_COMMAND
        if not isinstance(effective_command, bytes) or not effective_command:
            raise ValueError("command must be non-empty bytes")
        if b"\r" in effective_command or b"\n" in effective_command:
            raise ValueError("command must not contain line delimiters")
        if len(effective_command) > MAX_FRAME_BYTES:
            raise ValueError(
                f"command must not exceed {MAX_FRAME_BYTES} encoded bytes"
            )
        if fault_profile is not None and not isinstance(
            fault_profile,
            FaultProfile,
        ):
            raise TypeError("fault_profile must be FaultProfile or None")

        self.host = host.strip()
        self.port = port
        self._current_command = effective_command
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._state_lock = threading.Lock()
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._active = False
        self._startup_error: BaseException | None = None
        self._fault_profile = fault_profile if fault_profile is not None else FaultProfile()
        self._accepted_request_count = 0
        self._triggered_faults: list[FaultRule] = []

    @property
    def get_current_command(self) -> bytes:
        """Exact command accepted by this emulator instance."""

        return self._current_command

    @property
    def startup_error(self) -> BaseException | None:
        """Return a bind/listen error captured by the server thread, if any."""

        with self._state_lock:
            return self._startup_error

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._server_socket is not None and not self._stop_event.is_set()

    @property
    def server_thread(self) -> threading.Thread | None:
        """Return the owned worker thread for diagnostics and tests."""

        with self._state_lock:
            return self._thread

    @property
    def fault_profile(self) -> FaultProfile:
        return self._fault_profile

    @property
    def accepted_request_count(self) -> int:
        with self._state_lock:
            return self._accepted_request_count

    @property
    def triggered_faults(self) -> tuple[FaultRule, ...]:
        with self._state_lock:
            return tuple(self._triggered_faults)

    def start(
        self,
        timeout: float = DEFAULT_LIFECYCLE_TIMEOUT_SECONDS,
    ) -> AmmeterEmulatorBase:
        """Start the owned server thread and wait until bind/listen succeeds."""

        _validate_timeout(timeout)
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                raise AmmeterServerStartupError(
                    f"{type(self).__name__} server is already running"
                )
            if self._active:
                raise AmmeterServerStartupError(
                    f"{type(self).__name__} server is already active"
                )

            self._startup_error = None
            self._accepted_request_count = 0
            self._triggered_faults.clear()
            self._stop_event.clear()
            self._ready_event.clear()
            thread = threading.Thread(
                target=self._server_thread_entry,
                name=f"{type(self).__name__}-server",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except BaseException:
                self._thread = None
                raise

        if not self._ready_event.wait(timeout):
            self.stop(timeout)
            raise AmmeterServerStartupError(
                f"Timed out starting {type(self).__name__} at {self.host}:{self.port}"
            )

        startup_error = self.startup_error
        if startup_error is not None:
            self.stop(timeout)
            raise AmmeterServerStartupError(
                f"Failed to start {type(self).__name__} at "
                f"{self.host}:{self.port}: {startup_error}"
            ) from startup_error
        if not self.is_running:
            self.stop(timeout)
            raise AmmeterServerStartupError(
                f"{type(self).__name__} stopped before becoming ready"
            )
        return self

    def stop(
        self,
        timeout: float = DEFAULT_LIFECYCLE_TIMEOUT_SECONDS,
    ) -> None:
        """Stop and join the owned server thread. Calling repeatedly is safe."""

        _validate_timeout(timeout)
        self.stop_server()
        with self._state_lock:
            thread = self._thread

        if thread is None:
            self._ready_event.clear()
            return
        if thread is threading.current_thread():
            raise AmmeterServerShutdownError("A server thread cannot join itself")

        thread.join(timeout)
        if thread.is_alive():
            raise AmmeterServerShutdownError(
                f"Timed out stopping {type(self).__name__} at {self.host}:{self.port}"
            )

        with self._state_lock:
            if self._thread is thread:
                self._thread = None
        self._ready_event.clear()

    def start_server(self) -> None:
        """Run the blocking server loop until ``stop_server`` is requested."""

        with self._state_lock:
            if self._active:
                raise RuntimeError(f"{type(self).__name__} server is already active")
            self._active = True

        server_socket: socket.socket | None = None
        try:
            # Preserve a stop that arrived after start() created the worker but
            # before this function was scheduled. The worker must never clear it.
            if self._stop_event.is_set():
                self._ready_event.set()
                return

            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._configure_bind_semantics(server_socket)
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            server_socket.settimeout(ACCEPT_POLL_SECONDS)

            with self._state_lock:
                self.port = int(server_socket.getsockname()[1])
                self._server_socket = server_socket
            self._ready_event.set()
            LOGGER.info(
                "%s is listening on %s:%d",
                type(self).__name__,
                self.host,
                self.port,
            )

            while not self._stop_event.is_set():
                try:
                    connection, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise

                with connection:
                    connection.settimeout(CLIENT_IO_TIMEOUT_SECONDS)
                    self._handle_connection(connection, address)
        except BaseException as exc:
            with self._state_lock:
                self._startup_error = exc
            self._ready_event.set()
            raise
        finally:
            if server_socket is not None:
                server_socket.close()
            with self._state_lock:
                self._server_socket = None
                self._active = False

    def wait_until_ready(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for a successful bind/listen."""

        _validate_timeout(timeout)
        if not self._ready_event.wait(timeout):
            return False
        return self.startup_error is None and self.is_running

    def stop_server(self) -> None:
        """Request server-loop shutdown without joining the owned thread."""

        self._stop_event.set()

    @staticmethod
    def _configure_bind_semantics(server_socket: socket.socket) -> None:
        # Windows SO_REUSEADDR can permit two live listeners on one endpoint.
        # Exclusive binding prevents nondeterministic request routing. POSIX does
        # not have that behavior, and SO_REUSEADDR supports prompt test restarts.
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server_socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        else:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def _server_thread_entry(self) -> None:
        try:
            self.start_server()
        except BaseException:
            # start_server stores the error so start() can re-raise it in the
            # caller. Avoid an unhandled background-thread traceback.
            LOGGER.debug("Emulator server thread stopped with an error", exc_info=True)

    def _handle_connection(
        self,
        connection: socket.socket,
        address: tuple[str, int],
    ) -> None:
        try:
            command = self._receive_frame(connection)
            if command != self.get_current_command:
                self._send_frame(connection, b"ERROR unknown command")
                return

            fault = self._next_fault_rule()
            if fault is not None:
                if fault.kind is FaultKind.DISCONNECT:
                    return
                if fault.kind is FaultKind.ERROR_RESPONSE:
                    assert fault.error_message is not None
                    self._send_frame(
                        connection,
                        f"ERROR {fault.error_message}".encode("utf-8"),
                    )
                    return
                if fault.kind is FaultKind.MALFORMED_RESPONSE:
                    assert fault.response_payload is not None
                    self._send_frame(
                        connection,
                        fault.response_payload.encode("utf-8"),
                    )
                    return
                if fault.kind is FaultKind.RESPONSE_DELAY:
                    assert fault.delay_seconds is not None
                    if self._stop_event.wait(fault.delay_seconds):
                        return

            current = float(self.measure_current())
            if fault is not None and fault.kind is FaultKind.CURRENT_OFFSET:
                assert fault.current_offset_a is not None
                current += fault.current_offset_a
            if not math.isfinite(current):
                raise ValueError("measurement must be finite")
            self._send_frame(connection, repr(current).encode("ascii"))
        except (ConnectionError, OSError, ValueError) as exc:
            LOGGER.warning(
                "Rejected request from %s:%s: %s",
                address[0],
                address[1],
                exc,
            )
            self._send_frame(connection, f"ERROR {exc}".encode("utf-8"))
        except Exception:
            LOGGER.exception("Unexpected emulator error while handling %s", address)
            self._send_frame(connection, b"ERROR measurement failed")

    def _next_fault_rule(self) -> FaultRule | None:
        with self._state_lock:
            self._accepted_request_count += 1
            fault = self._fault_profile.rule_for(self._accepted_request_count)
            if fault is not None:
                self._triggered_faults.append(fault)
            return fault

    @staticmethod
    def _receive_frame(connection: socket.socket) -> bytes:
        buffer = bytearray()
        while True:
            chunk = connection.recv(min(256, MAX_FRAME_BYTES + 1 - len(buffer)))
            if not chunk:
                raise ValueError("request ended before newline delimiter")

            newline_index = chunk.find(b"\n")
            if newline_index >= 0:
                buffer.extend(chunk[:newline_index])
                trailing = chunk[newline_index + 1 :]
                if trailing:
                    raise ValueError("request contains data after newline delimiter")
                break

            buffer.extend(chunk)
            if len(buffer) > MAX_FRAME_BYTES:
                raise ValueError("request exceeds maximum frame size")

        if not buffer:
            raise ValueError("request command is empty")
        if b"\r" in buffer:
            raise ValueError("request contains an invalid carriage return")
        return bytes(buffer)

    @staticmethod
    def _send_frame(connection: socket.socket, payload: bytes) -> None:
        try:
            connection.sendall(payload + b"\n")
        except OSError:
            # The peer may already have disconnected after a malformed request.
            LOGGER.debug("Unable to send emulator response", exc_info=True)

    @abstractmethod
    def measure_current(self) -> float:
        """Return one current measurement in amperes."""

        raise NotImplementedError("Subclasses must implement measure_current().")


def _validate_timeout(timeout: float) -> None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive finite number")
