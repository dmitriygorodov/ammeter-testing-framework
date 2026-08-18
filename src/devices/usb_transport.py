"""Optional USB transport for command/response ammeters."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from Ammeters.faults import FaultKind, FaultProfile, FaultRule

from .constants import MAX_FRAME_BYTES
from .errors import (
    AmmeterClientError,
    AmmeterConnectionError,
    AmmeterProtocolError,
    AmmeterTimeoutError,
    AmmeterTransportDependencyError,
)


class UsbBackend(Protocol):
    """One USB exchange supplied by PyUSB, a vendor SDK, or a test double."""

    def exchange(
        self,
        *,
        vendor_id: int,
        product_id: int,
        serial_number: str | None,
        interface_number: int,
        alternate_setting: int,
        read_endpoint_address: int | None,
        write_endpoint_address: int | None,
        request_payload: bytes,
        max_response_bytes: int,
        timeout_ms: int,
    ) -> bytes:
        ...


class EmulatedUsbBackend:
    """In-process USB backend used when a USB ammeter is emulated.

    It implements the same exchange contract as :class:`PyUsbBackend`, so the
    command adapter and test framework exercise the USB path without requiring
    a physical device, an operating-system USB driver, or PyUSB.
    """

    def __init__(
        self,
        *,
        command: bytes,
        measurement_provider: Callable[[], float],
        fault_profile: FaultProfile | None = None,
    ) -> None:
        if not isinstance(command, bytes) or not command:
            raise ValueError("command must be non-empty bytes")
        if b"\r" in command or b"\n" in command:
            raise ValueError("command must not contain line delimiters")
        if not callable(measurement_provider):
            raise TypeError("measurement_provider must be callable")
        if fault_profile is not None and not isinstance(fault_profile, FaultProfile):
            raise TypeError("fault_profile must be FaultProfile or None")

        self._command = command
        self._measurement_provider = measurement_provider
        self._fault_profile = (
            fault_profile if fault_profile is not None else FaultProfile()
        )
        self._state_lock = threading.Lock()
        self._accepted_request_count = 0
        self._triggered_faults: list[FaultRule] = []

    @property
    def accepted_request_count(self) -> int:
        with self._state_lock:
            return self._accepted_request_count

    @property
    def triggered_faults(self) -> tuple[FaultRule, ...]:
        with self._state_lock:
            return tuple(self._triggered_faults)

    def exchange(
        self,
        *,
        vendor_id: int,
        product_id: int,
        serial_number: str | None,
        interface_number: int,
        alternate_setting: int,
        read_endpoint_address: int | None,
        write_endpoint_address: int | None,
        request_payload: bytes,
        max_response_bytes: int,
        timeout_ms: int,
    ) -> bytes:
        # Identity and endpoint arguments intentionally remain in this method's
        # signature: callers use exactly the same contract as the real backend.
        del (
            vendor_id,
            product_id,
            serial_number,
            interface_number,
            alternate_setting,
            read_endpoint_address,
            write_endpoint_address,
        )
        if request_payload != self._command + b"\n":
            return _limit_emulated_response(
                b"ERROR unknown command\n",
                max_response_bytes,
            )

        fault = self._next_fault_rule()
        if fault is not None:
            if fault.kind is FaultKind.DISCONNECT:
                raise OSError("emulated USB device disconnected")
            if fault.kind is FaultKind.ERROR_RESPONSE:
                assert fault.error_message is not None
                return _limit_emulated_response(
                    f"ERROR {fault.error_message}\n".encode("utf-8"),
                    max_response_bytes,
                )
            if fault.kind is FaultKind.MALFORMED_RESPONSE:
                assert fault.response_payload is not None
                return _limit_emulated_response(
                    fault.response_payload.encode("utf-8") + b"\n",
                    max_response_bytes,
                )
            if fault.kind is FaultKind.RESPONSE_DELAY:
                assert fault.delay_seconds is not None
                if fault.delay_seconds * 1000.0 > timeout_ms:
                    raise TimeoutError("emulated USB response exceeded timeout")
                time.sleep(fault.delay_seconds)

        try:
            current = float(self._measurement_provider())
        except Exception as exc:
            raise OSError(f"emulated USB measurement failed: {exc}") from exc
        if fault is not None and fault.kind is FaultKind.CURRENT_OFFSET:
            assert fault.current_offset_a is not None
            current += fault.current_offset_a
        if not math.isfinite(current):
            raise OSError("emulated USB measurement must be finite")
        return _limit_emulated_response(
            repr(current).encode("ascii") + b"\n",
            max_response_bytes,
        )

    def _next_fault_rule(self) -> FaultRule | None:
        with self._state_lock:
            self._accepted_request_count += 1
            fault = self._fault_profile.rule_for(self._accepted_request_count)
            if fault is not None:
                self._triggered_faults.append(fault)
            return fault


@dataclass(frozen=True, slots=True)
class UsbTransport:
    """LF-framed USB request/response transport with an injectable backend."""

    vendor_id: int
    product_id: int
    timeout_seconds: float
    serial_number: str | None = None
    interface_number: int = 0
    alternate_setting: int = 0
    read_endpoint_address: int | None = None
    write_endpoint_address: int | None = None
    max_frame_bytes: int = MAX_FRAME_BYTES
    backend: UsbBackend | None = None

    def __post_init__(self) -> None:
        _usb_identifier(self.vendor_id, "vendor_id")
        _usb_identifier(self.product_id, "product_id")
        _bounded_integer(
            self.interface_number,
            "interface_number",
            minimum=0,
            maximum=255,
        )
        _bounded_integer(
            self.alternate_setting,
            "alternate_setting",
            minimum=0,
            maximum=255,
        )
        _usb_endpoint(
            self.read_endpoint_address,
            "read_endpoint_address",
            input_endpoint=True,
        )
        _usb_endpoint(
            self.write_endpoint_address,
            "write_endpoint_address",
            input_endpoint=False,
        )
        if self.serial_number is not None and (
            not isinstance(self.serial_number, str)
            or not self.serial_number.strip()
            or self.serial_number != self.serial_number.strip()
            or any(
                delimiter in self.serial_number
                for delimiter in ("\x00", "\r", "\n")
            )
        ):
            raise ValueError("serial_number must be a clean non-empty string")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0.0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        _bounded_integer(
            self.max_frame_bytes,
            "max_frame_bytes",
            minimum=1,
            maximum=1_048_576,
        )
        effective_backend = self.backend if self.backend is not None else PyUsbBackend()
        if not callable(getattr(effective_backend, "exchange", None)):
            raise TypeError("backend must implement UsbBackend.exchange")
        object.__setattr__(self, "backend", effective_backend)

    @property
    def endpoint(self) -> str:
        serial = f"/{self.serial_number}" if self.serial_number is not None else ""
        return f"USB {self.vendor_id:#06x}:{self.product_id:#06x}{serial}"

    def request(self, command: bytes) -> bytes:
        self._validate_command(command)
        assert self.backend is not None
        try:
            response = self.backend.exchange(
                vendor_id=self.vendor_id,
                product_id=self.product_id,
                serial_number=self.serial_number,
                interface_number=self.interface_number,
                alternate_setting=self.alternate_setting,
                read_endpoint_address=self.read_endpoint_address,
                write_endpoint_address=self.write_endpoint_address,
                request_payload=command + b"\n",
                max_response_bytes=self.max_frame_bytes + 1,
                timeout_ms=max(1, math.ceil(float(self.timeout_seconds) * 1000.0)),
            )
        except AmmeterClientError:
            raise
        except TimeoutError as exc:
            raise AmmeterTimeoutError(
                f"Timed out communicating with ammeter at {self.endpoint}"
            ) from exc
        except OSError as exc:
            raise AmmeterConnectionError(
                f"Could not communicate with ammeter at {self.endpoint}: {exc}"
            ) from exc
        return self._extract_frame(response)

    def _validate_command(self, command: bytes) -> None:
        if not isinstance(command, bytes) or not command:
            raise ValueError("command must be non-empty bytes")
        if b"\r" in command or b"\n" in command:
            raise ValueError("command must not contain line delimiters")
        if len(command) > self.max_frame_bytes:
            raise ValueError(
                f"command must not exceed {self.max_frame_bytes} encoded bytes"
            )

    def _extract_frame(self, response: object) -> bytes:
        if not isinstance(response, bytes):
            raise AmmeterProtocolError("USB response payload must be bytes")
        newline_index = response.find(b"\n")
        if newline_index < 0:
            raise AmmeterProtocolError(
                "USB response ended before the newline delimiter"
            )
        payload = response[:newline_index]
        if response[newline_index + 1 :]:
            raise AmmeterProtocolError(
                "USB response contains data after the newline delimiter"
            )
        if len(payload) > self.max_frame_bytes:
            raise AmmeterProtocolError("USB response exceeds maximum frame size")
        if b"\r" in payload:
            raise AmmeterProtocolError(
                "USB response contains an invalid carriage return"
            )
        return payload


class PyUsbBackend:
    """Lazy PyUSB bulk/interrupt endpoint adapter.

    PyUSB is imported only when a USB-configured ammeter is read. TCP-only
    deployments therefore do not need the optional dependency or a USB driver.
    """

    def exchange(
        self,
        *,
        vendor_id: int,
        product_id: int,
        serial_number: str | None,
        interface_number: int,
        alternate_setting: int,
        read_endpoint_address: int | None,
        write_endpoint_address: int | None,
        request_payload: bytes,
        max_response_bytes: int,
        timeout_ms: int,
    ) -> bytes:
        try:
            import usb.core as usb_core
            import usb.util as usb_util
        except (ImportError, ModuleNotFoundError) as exc:
            raise AmmeterTransportDependencyError(
                "USB communication requires PyUSB. Install requirements-usb.txt "
                "and the platform USB backend/driver."
            ) from exc

        device: Any | None = None
        try:
            candidates = tuple(
                usb_core.find(
                    find_all=True,
                    idVendor=vendor_id,
                    idProduct=product_id,
                )
                or ()
            )
            if serial_number is not None:
                candidates = tuple(
                    candidate
                    for candidate in candidates
                    if _device_serial(candidate, usb_util) == serial_number
                )
            if not candidates:
                raise AmmeterConnectionError(
                    "USB ammeter was not found at "
                    f"{vendor_id:#06x}:{product_id:#06x}"
                )
            if len(candidates) > 1:
                raise AmmeterConnectionError(
                    "Multiple matching USB ammeters were found; configure a "
                    "serial_number"
                )
            device = candidates[0]
            device.set_configuration()
            configuration = device.get_active_configuration()
            interface = configuration[(interface_number, alternate_setting)]
            write_endpoint = _select_endpoint(
                interface,
                usb_util,
                address=write_endpoint_address,
                input_endpoint=False,
            )
            read_endpoint = _select_endpoint(
                interface,
                usb_util,
                address=read_endpoint_address,
                input_endpoint=True,
            )
            write_endpoint.write(request_payload, timeout=timeout_ms)
            return bytes(
                read_endpoint.read(max_response_bytes, timeout=timeout_ms)
            )
        except AmmeterClientError:
            raise
        except Exception as exc:
            timeout_error = getattr(usb_core, "USBTimeoutError", ())
            usb_error = getattr(usb_core, "USBError", ())
            if timeout_error and isinstance(exc, timeout_error):
                raise AmmeterTimeoutError(
                    "Timed out during the USB request/response exchange"
                ) from exc
            if usb_error and isinstance(exc, usb_error):
                raise AmmeterConnectionError(
                    f"USB communication failed: {exc}"
                ) from exc
            raise AmmeterConnectionError(
                f"Could not configure or access the USB ammeter: {exc}"
            ) from exc
        finally:
            if device is not None:
                try:
                    usb_util.dispose_resources(device)
                except Exception:
                    pass


def _device_serial(device: Any, usb_util: Any) -> str | None:
    serial_index = int(getattr(device, "iSerialNumber", 0) or 0)
    return None if serial_index == 0 else usb_util.get_string(device, serial_index)


def _select_endpoint(
    interface: Any,
    usb_util: Any,
    *,
    address: int | None,
    input_endpoint: bool,
) -> Any:
    if address is not None:
        endpoint = next(
            (
                candidate
                for candidate in interface
                if int(candidate.bEndpointAddress) == address
            ),
            None,
        )
    else:
        expected_direction = (
            usb_util.ENDPOINT_IN if input_endpoint else usb_util.ENDPOINT_OUT
        )
        endpoint = usb_util.find_descriptor(
            interface,
            custom_match=lambda candidate: usb_util.endpoint_direction(
                candidate.bEndpointAddress
            )
            == expected_direction,
        )
    if endpoint is None:
        direction = "IN" if input_endpoint else "OUT"
        raise AmmeterConnectionError(
            f"USB interface does not expose the requested {direction} endpoint"
        )
    return endpoint


def _usb_identifier(value: object, field_name: str) -> int:
    return _bounded_integer(
        value,
        field_name,
        minimum=1,
        maximum=0xFFFF,
    )


def _usb_endpoint(
    value: object,
    field_name: str,
    *,
    input_endpoint: bool,
) -> int | None:
    if value is None:
        return None
    endpoint = _bounded_integer(
        value,
        field_name,
        minimum=1,
        maximum=0xFF,
    )
    if bool(endpoint & 0x80) != input_endpoint:
        direction = "IN" if input_endpoint else "OUT"
        raise ValueError(f"{field_name} must be a USB {direction} endpoint")
    return endpoint


def _bounded_integer(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"{field_name} must be an integer from {minimum} through {maximum}"
        )
    return value


def _limit_emulated_response(response: bytes, maximum_bytes: int) -> bytes:
    _bounded_integer(
        maximum_bytes,
        "max_response_bytes",
        minimum=1,
        maximum=1_048_577,
    )
    return response[:maximum_bytes]
