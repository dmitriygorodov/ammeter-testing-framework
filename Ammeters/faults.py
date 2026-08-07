"""Deterministic emulator fault schedules for Phase 10 error simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


MAX_SIMULATED_PAYLOAD_BYTES = 1_024


class FaultKind(str, Enum):
    """Supported failures at the emulator protocol and measurement boundary."""

    RESPONSE_DELAY = "response_delay"
    ERROR_RESPONSE = "error_response"
    MALFORMED_RESPONSE = "malformed_response"
    DISCONNECT = "disconnect"
    CURRENT_OFFSET = "current_offset"


@dataclass(frozen=True, slots=True, kw_only=True)
class FaultRule:
    """Apply exactly one fault to one accepted measurement request."""

    request_number: int
    kind: FaultKind
    delay_seconds: float | None = None
    error_message: str | None = None
    response_payload: str | None = None
    current_offset_a: float | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.request_number, bool)
            or not isinstance(self.request_number, int)
            or self.request_number <= 0
        ):
            raise ValueError("request_number must be a positive integer")
        if not isinstance(self.kind, FaultKind):
            raise TypeError("kind must be FaultKind")

        supplied_fields = {
            "delay_seconds": self.delay_seconds,
            "error_message": self.error_message,
            "response_payload": self.response_payload,
            "current_offset_a": self.current_offset_a,
        }
        required_field = {
            FaultKind.RESPONSE_DELAY: "delay_seconds",
            FaultKind.ERROR_RESPONSE: "error_message",
            FaultKind.MALFORMED_RESPONSE: "response_payload",
            FaultKind.DISCONNECT: None,
            FaultKind.CURRENT_OFFSET: "current_offset_a",
        }[self.kind]
        unexpected = tuple(
            field_name
            for field_name, value in supplied_fields.items()
            if value is not None and field_name != required_field
        )
        if unexpected:
            raise ValueError(
                f"{self.kind.value} does not accept: " + ", ".join(unexpected)
            )
        if required_field is not None and supplied_fields[required_field] is None:
            raise ValueError(f"{self.kind.value} requires {required_field}")

        if self.kind is FaultKind.RESPONSE_DELAY:
            delay = _finite_number(self.delay_seconds, "delay_seconds")
            if delay <= 0.0:
                raise ValueError("delay_seconds must be positive")
            object.__setattr__(self, "delay_seconds", delay)
        elif self.kind is FaultKind.ERROR_RESPONSE:
            assert self.error_message is not None
            _validate_text(
                self.error_message,
                "error_message",
                allow_empty=False,
            )
            if len(("ERROR " + self.error_message).encode("utf-8")) > MAX_SIMULATED_PAYLOAD_BYTES:
                raise ValueError("error_message exceeds the maximum response size")
        elif self.kind is FaultKind.MALFORMED_RESPONSE:
            assert self.response_payload is not None
            _validate_text(
                self.response_payload,
                "response_payload",
                allow_empty=True,
            )
            encoded = self.response_payload.encode("utf-8")
            if len(encoded) > MAX_SIMULATED_PAYLOAD_BYTES:
                raise ValueError("response_payload exceeds the maximum response size")
            if self.response_payload.startswith("ERROR "):
                raise ValueError(
                    "malformed_response must not be an explicit ERROR response"
                )
            try:
                numeric_payload = float(self.response_payload)
            except ValueError:
                pass
            else:
                if math.isfinite(numeric_payload):
                    raise ValueError(
                        "malformed_response payload must not be a finite number"
                    )
        elif self.kind is FaultKind.CURRENT_OFFSET:
            offset = _finite_number(self.current_offset_a, "current_offset_a")
            if offset == 0.0:
                raise ValueError("current_offset_a must be nonzero")
            object.__setattr__(self, "current_offset_a", offset)


@dataclass(frozen=True, slots=True)
class FaultProfile:
    """Ordered, non-repeating fault rules for one emulator session."""

    rules: tuple[FaultRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.rules, tuple) or not all(
            isinstance(rule, FaultRule) for rule in self.rules
        ):
            raise TypeError("rules must be a tuple of FaultRule records")
        request_numbers = tuple(rule.request_number for rule in self.rules)
        if len(set(request_numbers)) != len(request_numbers):
            raise ValueError("Fault rule request numbers must be unique")
        if request_numbers != tuple(sorted(request_numbers)):
            raise ValueError("Fault rules must be ordered by request number")

    def rule_for(self, request_number: int) -> FaultRule | None:
        if (
            isinstance(request_number, bool)
            or not isinstance(request_number, int)
            or request_number <= 0
        ):
            raise ValueError("request_number must be a positive integer")
        for rule in self.rules:
            if rule.request_number == request_number:
                return rule
            if rule.request_number > request_number:
                break
        return None


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be a finite number")
    return 0.0 if normalized == 0.0 else normalized


def _validate_text(value: object, field_name: str, *, allow_empty: bool) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have surrounding whitespace")
    if any(delimiter in value for delimiter in ("\x00", "\r", "\n")):
        raise ValueError(f"{field_name} must not contain control delimiters")
