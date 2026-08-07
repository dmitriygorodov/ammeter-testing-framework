"""Phase 9 facade delegation remains independent of devices and archives."""

from __future__ import annotations

import unittest

from src.testing.test_framework import AmmeterTestFramework


class _NoDeviceRegistry:
    names: tuple[str, ...] = ()

    def get(self, name: str) -> object:
        raise AssertionError(f"Visualization must not access hardware: {name}")


class _RecordingVisualizer:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __bool__(self) -> bool:
        return False

    def plot_run_overview(self, result: object, *, verdict: object = None) -> object:
        self.calls.append(("run", result, verdict))
        return "run-figure"

    def plot_accuracy_assessment(self, assessment: object) -> object:
        self.calls.append(("accuracy", assessment))
        return "accuracy-figure"

    def plot_consistency_assessment(self, assessment: object) -> object:
        self.calls.append(("consistency", assessment))
        return "consistency-figure"

    def save(self, figure: object, output_path: object, *, dpi: int) -> object:
        self.calls.append(("save", figure, output_path, dpi))
        return "saved-path"


class VisualizationFrameworkTests(unittest.TestCase):
    def test_falsey_visualizer_is_honored_and_each_method_delegates_once(self) -> None:
        visualizer = _RecordingVisualizer()
        framework = AmmeterTestFramework(
            registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
            result_visualizer=visualizer,  # type: ignore[arg-type]
        )
        result = object()
        verdict = object()
        accuracy = object()
        consistency = object()

        self.assertEqual(
            framework.visualize_result(result, verdict=verdict),  # type: ignore[arg-type]
            "run-figure",
        )
        self.assertEqual(
            framework.visualize_accuracy(accuracy),  # type: ignore[arg-type]
            "accuracy-figure",
        )
        self.assertEqual(
            framework.visualize_consistency(consistency),  # type: ignore[arg-type]
            "consistency-figure",
        )
        self.assertEqual(
            framework.save_visualization("figure", "plot.png", dpi=240),
            "saved-path",
        )
        self.assertEqual(
            visualizer.calls,
            [
                ("run", result, verdict),
                ("accuracy", accuracy),
                ("consistency", consistency),
                ("save", "figure", "plot.png", 240),
            ],
        )

    def test_incomplete_visualizer_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "result_visualizer"):
            AmmeterTestFramework(
                registry=_NoDeviceRegistry(),  # type: ignore[arg-type]
                result_visualizer=object(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
