"""Deterministic scheduling tests for Phase 3's sampling runner."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.devices.models import CurrentMeasurement
from src.testing.models import SamplingPlan, SamplingStopReason
from src.testing.sampling import SamplingRunner


BASE_UTC = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


class _ManualClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.initial = initial
        self.current = initial

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class _AdvancingSleeper:
    def __init__(
        self,
        clock: _ManualClock,
        *,
        maximum_advance_seconds: float | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.clock = clock
        self.maximum_advance_seconds = maximum_advance_seconds
        self.error = error
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.error is not None:
            raise self.error
        advance = seconds
        if self.maximum_advance_seconds is not None:
            advance = min(advance, self.maximum_advance_seconds)
        self.clock.advance(advance)


class _TimedFakeAmmeter:
    def __init__(
        self,
        clock: _ManualClock,
        durations: list[float],
        *,
        name: str = "greenlee",
        failure_call: int | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.name = name
        self._clock = clock
        self._durations = durations
        self._failure_call = failure_call
        self._error = error
        self.read_starts: list[float] = []
        self.calls = 0

    def read_current(self) -> CurrentMeasurement:
        self.calls += 1
        self.read_starts.append(self._clock.current)
        if self.calls == self._failure_call:
            assert self._error is not None
            raise self._error

        duration = self._durations[self.calls - 1]
        self._clock.advance(duration)
        return CurrentMeasurement(
            ammeter_name=self.name,
            current_a=float(self.calls),
            measured_at_utc=BASE_UTC
            + timedelta(seconds=self._clock.current - self._clock.initial),
            monotonic_time_s=self._clock.current,
            latency_seconds=duration,
        )


def _runner(
    clock: _ManualClock,
    sleeper: _AdvancingSleeper,
) -> SamplingRunner:
    return SamplingRunner(
        monotonic_clock=clock,
        wall_clock=lambda: BASE_UTC
        + timedelta(seconds=clock.current - clock.initial),
        sleeper=sleeper,
    )


class SamplingRunnerTests(unittest.TestCase):
    def assertFloatSequenceAlmostEqual(
        self,
        actual: list[float] | tuple[float, ...],
        expected: list[float] | tuple[float, ...],
    ) -> None:
        self.assertEqual(len(actual), len(expected))
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value)

    def test_count_cap_collects_exact_count_on_absolute_cadence(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.1, 0.2, 0.05])
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=3)

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(result.stop_reason, SamplingStopReason.COUNT_REACHED)
        self.assertEqual(result.sample_count, 3)
        self.assertFloatSequenceAlmostEqual(
            ammeter.read_starts,
            [100.0, 100.5, 101.0],
        )
        self.assertFloatSequenceAlmostEqual(sleeper.calls, [0.4, 0.3])
        self.assertFloatSequenceAlmostEqual(
            [sample.scheduled_offset_seconds for sample in result.samples],
            [0.0, 0.5, 1.0],
        )
        self.assertFloatSequenceAlmostEqual(
            [sample.completed_offset_seconds for sample in result.samples],
            [0.1, 0.7, 1.05],
        )
        self.assertEqual(result.started_at_utc, BASE_UTC)
        self.assertEqual(
            result.completed_at_utc,
            BASE_UTC + timedelta(seconds=1.05),
        )
        self.assertAlmostEqual(result.started_monotonic_s, 100.0)
        self.assertAlmostEqual(result.completed_monotonic_s, 101.05)
        self.assertAlmostEqual(result.elapsed_seconds, 1.05)

    def test_invalid_padded_device_name_is_rejected_before_acquisition(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.0], name=" greenlee ")
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=1)

        with self.assertRaises(TypeError):
            _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(ammeter.calls, 0)

    def test_one_count_sample_is_immediate_and_never_sleeps(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.2])
        plan = SamplingPlan(sampling_frequency_hz=50.0, measurements_count=1)

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(ammeter.read_starts, [100.0])
        self.assertEqual(sleeper.calls, [])
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.stop_reason, SamplingStopReason.COUNT_REACHED)

    def test_duration_window_is_half_open(self) -> None:
        for duration, expected_starts in (
            (1.0, [100.0, 100.5]),
            (1.01, [100.0, 100.5, 101.0]),
        ):
            with self.subTest(duration=duration):
                clock = _ManualClock()
                sleeper = _AdvancingSleeper(clock)
                ammeter = _TimedFakeAmmeter(clock, [0.0, 0.0, 0.0])
                plan = SamplingPlan(
                    sampling_frequency_hz=2.0,
                    total_duration_seconds=duration,
                )

                result = _runner(clock, sleeper).run(ammeter, plan)

                self.assertFloatSequenceAlmostEqual(
                    ammeter.read_starts,
                    expected_starts,
                )
                self.assertEqual(
                    result.stop_reason,
                    SamplingStopReason.DURATION_REACHED,
                )

    def test_immediate_first_read_is_kept_when_it_finishes_after_duration(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.2])
        plan = SamplingPlan(
            sampling_frequency_hz=100.0,
            total_duration_seconds=0.05,
        )

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(ammeter.read_starts, [100.0])
        self.assertEqual(result.sample_count, 1)
        self.assertAlmostEqual(result.samples[0].completed_offset_seconds, 0.2)
        self.assertEqual(result.stop_reason, SamplingStopReason.DURATION_REACHED)

    def test_combined_caps_stop_at_whichever_cap_is_reached_first(self) -> None:
        cases = (
            (2, 10.0, 2, SamplingStopReason.COUNT_REACHED),
            (10, 0.75, 2, SamplingStopReason.DURATION_REACHED),
        )
        for count, duration, expected_count, expected_reason in cases:
            with self.subTest(count=count, duration=duration):
                clock = _ManualClock()
                sleeper = _AdvancingSleeper(clock)
                ammeter = _TimedFakeAmmeter(clock, [0.0] * 10)
                plan = SamplingPlan(
                    sampling_frequency_hz=2.0,
                    measurements_count=count,
                    total_duration_seconds=duration,
                )

                result = _runner(clock, sleeper).run(ammeter, plan)

                self.assertEqual(result.sample_count, expected_count)
                self.assertEqual(result.stop_reason, expected_reason)

    def test_duration_wins_if_it_expires_during_the_final_count_read(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.3, 0.3])
        plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            measurements_count=2,
            total_duration_seconds=0.5,
        )

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(result.sample_count, 2)
        self.assertAlmostEqual(result.samples[-1].completed_offset_seconds, 0.6)
        self.assertEqual(result.stop_reason, SamplingStopReason.DURATION_REACHED)

    def test_overrun_uses_original_schedule_without_negative_sleeps(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.25, 0.25, 0.25])
        plan = SamplingPlan(sampling_frequency_hz=10.0, measurements_count=3)

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(sleeper.calls, [])
        self.assertFloatSequenceAlmostEqual(
            ammeter.read_starts,
            [100.0, 100.25, 100.5],
        )
        self.assertFloatSequenceAlmostEqual(
            [sample.scheduled_offset_seconds for sample in result.samples],
            [0.0, 0.1, 0.2],
        )
        self.assertFloatSequenceAlmostEqual(
            [sample.start_lateness_seconds for sample in result.samples],
            [0.0, 0.15, 0.3],
        )

    def test_duration_overrun_does_not_start_another_read_after_deadline(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        ammeter = _TimedFakeAmmeter(clock, [0.3, 0.3, 0.3])
        plan = SamplingPlan(
            sampling_frequency_hz=10.0,
            total_duration_seconds=0.5,
        )

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertFloatSequenceAlmostEqual(ammeter.read_starts, [100.0, 100.3])
        self.assertEqual(result.sample_count, 2)
        self.assertEqual(result.stop_reason, SamplingStopReason.DURATION_REACHED)
        self.assertEqual(sleeper.calls, [])

    def test_early_returning_sleeper_is_retried_until_absolute_deadline(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock, maximum_advance_seconds=0.3)
        ammeter = _TimedFakeAmmeter(clock, [0.0, 0.0])
        plan = SamplingPlan(sampling_frequency_hz=1.0, measurements_count=2)

        result = _runner(clock, sleeper).run(ammeter, plan)

        self.assertEqual(result.sample_count, 2)
        self.assertAlmostEqual(ammeter.read_starts[1], 101.0)
        self.assertGreaterEqual(len(sleeper.calls), 4)
        self.assertTrue(all(requested > 0 for requested in sleeper.calls))

    def test_measurement_failure_propagates_unchanged_and_stops_sampling(self) -> None:
        clock = _ManualClock()
        sleeper = _AdvancingSleeper(clock)
        failure = RuntimeError("simulated device failure")
        ammeter = _TimedFakeAmmeter(
            clock,
            [0.0, 0.0, 0.0],
            failure_call=2,
            error=failure,
        )
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=3)

        with self.assertRaises(RuntimeError) as raised:
            _runner(clock, sleeper).run(ammeter, plan)

        self.assertIs(raised.exception, failure)
        self.assertEqual(ammeter.calls, 2)
        self.assertEqual(len(sleeper.calls), 1)

    def test_sleep_failure_propagates_unchanged_before_next_measurement(self) -> None:
        clock = _ManualClock()
        failure = RuntimeError("simulated sleeper failure")
        sleeper = _AdvancingSleeper(clock, error=failure)
        ammeter = _TimedFakeAmmeter(clock, [0.0, 0.0])
        plan = SamplingPlan(sampling_frequency_hz=2.0, measurements_count=2)

        with self.assertRaises(RuntimeError) as raised:
            _runner(clock, sleeper).run(ammeter, plan)

        self.assertIs(raised.exception, failure)
        self.assertEqual(ammeter.calls, 1)
        self.assertEqual(len(sleeper.calls), 1)


if __name__ == "__main__":
    unittest.main()
