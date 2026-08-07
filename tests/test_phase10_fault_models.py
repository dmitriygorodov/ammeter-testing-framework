"""Phase 10 deterministic fault model invariants."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

from Ammeters.faults import FaultKind, FaultProfile, FaultRule


class FaultRuleTests(unittest.TestCase):
    def test_each_supported_fault_has_one_typed_parameter_contract(self) -> None:
        rules = (
            FaultRule(
                request_number=1,
                kind=FaultKind.RESPONSE_DELAY,
                delay_seconds=0.25,
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
            FaultRule(
                request_number=5,
                kind=FaultKind.CURRENT_OFFSET,
                current_offset_a=-0.5,
            ),
        )

        profile = FaultProfile(rules)

        self.assertEqual(profile.rule_for(3), rules[2])
        self.assertIsNone(profile.rule_for(6))
        with self.assertRaises(FrozenInstanceError):
            rules[0].request_number = 9  # type: ignore[misc]

    def test_empty_and_nonfinite_malformed_payloads_are_valid_faults(self) -> None:
        for payload in ("", "not-a-number", "nan", "inf"):
            with self.subTest(payload=payload):
                rule = FaultRule(
                    request_number=1,
                    kind=FaultKind.MALFORMED_RESPONSE,
                    response_payload=payload,
                )
                self.assertEqual(rule.response_payload, payload)

    def test_rule_rejects_wrong_missing_and_unsafe_parameters(self) -> None:
        invalid_calls = (
            lambda: FaultRule(request_number=0, kind=FaultKind.DISCONNECT),
            lambda: FaultRule(  # type: ignore[arg-type]
                request_number=True,
                kind=FaultKind.DISCONNECT,
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.RESPONSE_DELAY,
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.RESPONSE_DELAY,
                delay_seconds=math.inf,
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.ERROR_RESPONSE,
                error_message=" padded ",
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.MALFORMED_RESPONSE,
                response_payload="12.5",
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.MALFORMED_RESPONSE,
                response_payload="ERROR different fault",
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.CURRENT_OFFSET,
                current_offset_a=0.0,
            ),
            lambda: FaultRule(
                request_number=1,
                kind=FaultKind.DISCONNECT,
                delay_seconds=1.0,
            ),
        )
        for call in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaises((TypeError, ValueError)):
                    call()

    def test_profile_requires_unique_ascending_request_numbers(self) -> None:
        first = FaultRule(request_number=1, kind=FaultKind.DISCONNECT)
        second = FaultRule(request_number=2, kind=FaultKind.DISCONNECT)
        with self.assertRaisesRegex(ValueError, "ordered"):
            FaultProfile((second, first))
        with self.assertRaisesRegex(ValueError, "unique"):
            FaultProfile((first, first))
        with self.assertRaises(ValueError):
            FaultProfile().rule_for(0)


if __name__ == "__main__":
    unittest.main()
