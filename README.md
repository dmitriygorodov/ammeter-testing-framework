# Ammeter ATE Testing Framework

This project is an automated-test-equipment exercise built around three supplied
TCP ammeter emulators: Greenlee, ENTES, and CIRCUTOR.

- Phase 1 established reliable emulator communication and lifecycle management.
- Phase 2 added a unified device API, typed measurements, transport separation,
  configuration-driven construction, and a registry.
- Phase 3 adds configurable fixed-rate sampling with drift-resistant monotonic
  scheduling and timing-rich immutable run results.
- Phase 4 adds dependency-free statistical analysis with immutable, JSON-ready
  summaries while preserving the complete Phase 3 sampling evidence.
- Phase 5 adds versioned JSON result archiving with UUID run identities, typed
  metadata, integrity verification, retrieval, filtering, and history comparison.
- Phase 6 adds reference-based cross-ammeter accuracy, precision, pairwise
  agreement, and RMSE reliability assessment from compatible archived evidence.
- Phase 7 adds configuration-driven, full-precision PASS/FAIL verdicts with
  versioned policies, explicit reference provenance, per-ammeter overrides, and
  electrical, statistical, and timing limits.
- Phase 8 adds read-only historical performance-consistency assessment with
  run-to-run variation, pooled repeatability, worst-step, and least-squares
  drift metrics from strictly comparable archived runs.
- Phase 9 adds headless run, accuracy, and consistency visualizations with
  tolerance overlays and explicit, non-overwriting PNG/SVG/PDF export.
- Phase 10 adds deterministic, configuration-driven emulator error simulation
  for delays, instrument errors, malformed payloads, disconnects, and finite
  measurement offsets.

## Requirements

- Python 3.10 or newer
- PyYAML 6.x
- Matplotlib 3.8 or newer

Install the runtime dependencies from the project directory:

```shell
python -m pip install -r requirements.txt
```

## Cross-platform support

The supported operating systems are Windows, Linux, and macOS. The repository's
GitHub Actions matrix runs the complete hardware-free suite on all three using
both the minimum supported Python 3.10 and Python 3.13. Run the same verification
locally from the project root on any platform:

```shell
python -B -m unittest discover -s tests -v
```

Platform-neutral behavior is deliberate: paths use `pathlib`, text artifacts
use explicit UTF-8 and LF framing, timestamps use UTC, plots use Matplotlib's
headless Agg renderer, and emulator sockets use Windows-exclusive or POSIX
reusable bind semantics as appropriate. Runtime code does not require shell
commands, POSIX signals, a GUI session, or platform-specific absolute paths.

## Run the one-shot demo

```shell
python main.py
```

The demo starts all three local emulators, waits until their sockets are ready,
collects one measurement from each, and always shuts every server down. Values
change on every run because the supplied emulators generate random test inputs.

```text
Ammeter measurements:
  GREENLEE 0.077026 A
  ENTES    91.199910 A
  CIRCUTOR 0.041805 A
```

The process exits only after all servers have stopped, so it can be run again
immediately without occupied-port errors.

## Run the Phase 3 sampling demo

The standalone example starts the local emulators and applies the sampling plan
from `config/config.yaml` to each one:

```shell
python -m examples.run_sampling_test
```

The existing one-shot example remains available:

```shell
python -m examples.run_tests
```

## Run the Phase 4 analysis demo

The Phase 4 example samples every local emulator and reports all five required
current metrics:

```shell
python -m examples.run_analysis_test
```

Values are retained at full precision in the result model. The example rounds
only its human-readable console output.

## Run the Phase 5 archive demo

The archive example performs acquisition, analysis, and persistence for all
three local emulators:

```shell
python -m examples.run_archive_test
```

By default, completed runs are written below `results/` using the configured
archive path. Each successful run creates one `<uuid>.json` file in a directory
derived from its assessment metadata:

```text
results/
  accuracy/group-<comparison-group>-<digest>/<uuid>.json
  consistency/group-<consistency-group>-<digest>/<uuid>.json
  general/<uuid>.json
```

The readable slug is path-safe and its short digest prevents two distinct group
names from collapsing onto the same folder. The full, original group value in
the JSON metadata remains authoritative. Existing root-level `<uuid>.json`
archives remain loadable and listable; reads never move them automatically.
Callers still load a run by UUID, without needing to know its folder.

Acquisition or analysis failures are never represented as completed archives.
One demo invocation assigns all three results a unique shared
`comparison_group`, so their UUIDs can be passed directly to the accuracy
commands. Supply a meaningful bench identity when one exists:

```shell
python -m examples.run_archive_test --comparison-group calibrated-1A-setup
```

## Run a Phase 6 accuracy assessment

Phase 6 consumes existing archives and requires a known reference current with
source provenance. It never reads an ammeter or changes an archive:

```shell
python -m examples.run_accuracy_assessment --reference-current-a 1.0 --reference-source "calibrated 1 A source" <greenlee-run-uuid> <entes-run-uuid> <circutor-run-uuid>
```

Grouped source runs must contain the same string-valued `comparison_group`
metadata and must identify the same test, DUT, station, sampling plan, sample
count, and stop reason. At least two samples and two distinct ammeters are
required. For backward compatibility, an explicit UUID selection is also
accepted when every selected legacy archive lacks `comparison_group`; the report
labels that cohort `explicit-ungrouped-run-selection`. Mixing grouped and
ungrouped archives remains an error.

## Run a Phase 7 acceptance test

Phase 7 requires an explicit `testing.acceptance` policy in the selected YAML
file. The project default leaves it `null` because the three supplied emulators
do not observe one common current and no defensible universal limits were
provided.

```shell
python -m examples.run_acceptance_demo --config path/to/bench-config.yaml
```

Use `--ammeter greenlee` to run one configured instrument. The command exits
with `0` when every verdict passes, `2` for a valid failing verdict, and a normal
exception path for configuration, acquisition, or analysis errors.

## Run a Phase 8 consistency assessment

Phase 8 consumes three or more archived runs and never reads hardware or changes
the archive:

```shell
python -m examples.run_consistency_assessment <run-uuid-1> <run-uuid-2> <run-uuid-3>
```

Use `--archive-directory path/to/archive` to bypass configuration loading. Each
run must carry the same nonempty string-valued `consistency_group` metadata and
must match on ammeter, test name, DUT, station, sampling plan, sample count, and
stop reason. Completion timestamps must be unique and each run needs at least
two samples.

## Render Phase 9 visualizations

Phase 9 renders existing evidence without starting an emulator or changing an
archive. Supply an explicit output path:

```shell
python -m examples.render_visualization run_overview <run-uuid> --output plots/run.png
python -m examples.render_visualization accuracy <run-uuid-1> <run-uuid-2> --reference-current-a 1.0 --reference-source "calibrated 1 A source" --output plots/accuracy.svg
python -m examples.render_visualization consistency <run-uuid-1> <run-uuid-2> <run-uuid-3> --output plots/consistency.pdf
```

The run overview combines current over time, a histogram, and scheduling
timing. A matching Phase 7 verdict may be passed through the framework API to
overlay configured current, reference, and timing limits. Accuracy plots show
mean plus population deviation, reference uncertainty, absolute error, and
RMSE. Consistency plots show chronological means, least-squares drift, and
within-run repeatability.

`ResultVisualizer` uses Matplotlib's object-oriented Agg renderer, so these
commands work on headless CI and ATE controllers. Export accepts only PNG, SVG,
or PDF, validates DPI from 72 through 600, and refuses to overwrite a file.

## Run a Phase 10 fault scenario

Fault injection is disabled in the default configuration. One runnable example
defines the same deterministic overcurrent scenario for all three emulators and
demonstrates that valid but extreme current becomes a Phase 7 `FAIL`, not an
execution error:

```shell
python -m examples.run_acceptance_demo --config config/fault-scenario.example.yaml --ammeter greenlee
python -m examples.run_acceptance_demo --config config/fault-scenario.example.yaml --ammeter entes
python -m examples.run_acceptance_demo --config config/fault-scenario.example.yaml --ammeter circutor
```

Omit `--ammeter` to evaluate all three in one invocation. Each command exits
with status `2` because the simulated current exceeds the explicit limit.
Protocol and transport faults instead raise the existing typed client errors
and cannot create a completed archive.

Rules are scheduled by one-based accepted measurement-request number. They
restart from request 1 whenever the emulator starts; unknown commands do not
advance them. Available rule shapes are:

```yaml
emulation:
  fault_injection:
    enabled: true
    ammeters:
      greenlee:
        - {request_number: 1, type: response_delay, delay_seconds: 1.5}
        - {request_number: 2, type: error_response, error_message: "simulated ADC fault"}
        - {request_number: 3, type: malformed_response, response_payload: "nan"}
        - {request_number: 4, type: disconnect}
        - {request_number: 5, type: current_offset, current_offset_a: 0.25}
```

Each request can have at most one rule. Delay faults remain interruptible during
emulator shutdown. Malformed payloads must actually be invalid or non-finite;
finite values belong to `current_offset`, preserving the difference between bad
protocol execution and valid out-of-tolerance evidence.

## Use the framework

When the configured instrument or emulator is already running, `run_test()` uses
the default YAML sampling plan:

```python
from src.testing.test_framework import AmmeterTestFramework

framework = AmmeterTestFramework()
result = framework.run_test("greenlee")

for sample in result.samples:
    print(
        sample.sample_index,
        sample.measurement.current_a,
        sample.measurement.unit,
        sample.start_lateness_seconds,
    )
```

An explicit plan overrides the YAML default:

```python
from src.testing.models import SamplingPlan

plan = SamplingPlan(
    sampling_frequency_hz=10.0,
    measurements_count=20,
    total_duration_seconds=5.0,
)
result = framework.run_test("greenlee", plan)
```

Count and duration are independent maximums. When both are supplied, the first
one reached stops the run. `measure_once()` and `measure_all_once()` remain
available for callers that do not need sampling.

The framework deliberately does not start or stop instruments. Lifecycle belongs
to the application, fixture, or lab-orchestration layer.

## Analyze completed runs

`run_analyzed_test()` performs one Phase 3 run and returns the original evidence
paired with its statistical summary:

```python
analyzed = framework.run_analyzed_test("greenlee")
statistics = analyzed.statistics

print(statistics.mean_current_a)
print(statistics.median_current_a)
print(statistics.standard_deviation_current_a)
print(statistics.minimum_current_a)
print(statistics.maximum_current_a)
```

Already-acquired or restored evidence can be analyzed without touching the
instrument again:

```python
run = framework.run_test("greenlee")
statistics = framework.analyze_result(run)
```

The analyzer includes every successful sample exactly once and never mutates or
reorders the source run. An empty run is rejected with `ResultAnalysisError`.
The stored standard deviation is the population standard deviation (`pstdev`):
the completed run is treated as the full acquired dataset, so one sample has a
standard deviation of `0.0 A`.

Phase 4 always computes the five metrics required by the exercise. The
`analysis.visualization` block controls optional Phase 9 default destinations;
it does not alter calculation or evidence.

## Archive and retrieve results

Archive metadata is typed, immutable, and kept separate from acquired evidence:

```python
from src.testing.archive_models import RunMetadata

metadata = RunMetadata(
    operator="Dima",
    dut_id="DUT-001",
    station_id="ATE-01",
    tags=("nightly", "release-candidate"),
)
archived = framework.run_archived_test(
    "greenlee",
    metadata=metadata,
)
print(archived.run_id)
```

Existing analyzed evidence can be archived without another instrument read:

```python
analyzed = framework.run_analyzed_test("greenlee")
archived = framework.archive_result(analyzed, metadata)
```

Runs remain available to a new process or framework instance:

```python
restored = framework.load_archived_result(archived.run_id)
greenlee_history = framework.list_archived_results(
    ammeter_name="greenlee",
    tag="nightly",
)
```

Phase 5 comparisons operate on two runs from the same ammeter and the same
metadata `test_name`. Every delta is `candidate - baseline`, and differing
sampling plans are reported rather than silently hidden:

```python
comparison = framework.compare_archived_results(
    baseline_run_id,
    candidate_run_id,
)
print(comparison.mean_current_delta_a)
print(comparison.sampling_plans_match)
```

Same-ammeter historical comparison remains separate from the Phase 6
cross-ammeter accuracy assessment described below.

### Archive integrity

Archive files use schema version 1 and contain the complete raw sampling evidence,
the derived statistics, run metadata, UTC archive time, completion status, and a
canonical SHA-256 digest. Loading is a strict trust boundary: duplicate keys,
non-finite JSON numbers, unexpected fields, altered units or timing derivatives,
unsupported schemas, filename/payload ID mismatches, and checksum failures are
rejected. Statistics are also recomputed from restored samples, so changing a
summary and recalculating its checksum still does not create valid evidence.

Writes use a unique temporary file in the selected group directory, flush it,
and atomically link it to the final UUID path. Hard-link creation fails if that
path already exists. A root-level reservation file and a whole-tree UUID check
prevent cooperating writers from claiming the same run ID in different groups.

The archive directory is a local, operator-controlled data store rather than an
adversarial upload area. SHA-256 detects accidental edits and inconsistent
evidence; it is not an authenticity signature. Deployments with untrusted
writers should add restrictive directory permissions, bounded file sizes, and
an HMAC or digital-signature policy.

## Assess cross-ammeter accuracy and precision

The comparison group is persisted with every run so the stable-stimulus claim is
auditable rather than inferred from timestamps:

```python
from src.testing import ReferenceCurrent, RunMetadata

metadata = RunMetadata(
    test_name="one_ampere_reference",
    dut_id="DUT-001",
    station_id="ATE-01",
    attributes=(("comparison_group", "calibration-2026-08-06-a"),),
)

# Acquire/archive each ammeter with the same metadata and SamplingPlan.
assessment = framework.assess_archived_accuracy(
    (greenlee_run_id, entes_run_id, circutor_run_id),
    reference=ReferenceCurrent(
        current_a=1.0,
        source="calibrated current source asset CS-17",
        expanded_uncertainty_a=0.001,
        calibration_id="CERT-2026-1042",
    ),
)

print(assessment.most_accurate_ammeters)
print(assessment.most_precise_ammeters)
print(assessment.most_reliable_ammeters)
```

For each ammeter, Phase 6 reports:

- signed bias: `mean - reference`;
- absolute error and, for a nonzero reference, relative error percent;
- population standard deviation as within-run precision;
- reference RMSE: `hypot(bias, standard_deviation)`;
- separate accuracy, precision, and reliability ranks.

Lower values rank first. Competition ranking preserves every exact tie (for
example `1, 1, 3`), and output ordering is deterministic. Pairwise records use
`second mean - first mean`. Metrics retain full precision; only the text reporter
formats values for display.

Accuracy means accuracy relative to the supplied reference. Without a calibrated
and traceable source, the result is not an absolute metrology claim. The RMSE
ranking describes reference fidelity during these successful runs; it does not
measure failure rate or long-term reliability.

The supplied Greenlee, ENTES, and CIRCUTOR emulators generate unrelated random
physical calculations and are sampled sequentially. Their default outputs must
not be presented as a real accuracy contest. Use scripted common-reference
evidence, or a lab setup where every ammeter observes the same stable current.

## Evaluate configuration-driven acceptance limits

An acceptance policy can check any combination of observed range, mean bias,
relative mean error, population standard deviation, worst start lateness, and
worst acquisition duration:

```python
from src.testing.acceptance_models import AcceptanceLimits, AcceptancePolicy
from src.testing.accuracy_models import ReferenceCurrent

policy = AcceptancePolicy(
    name="bench-current",
    version="2026.1",
    reference=ReferenceCurrent(
        current_a=1.0,
        source="calibrated current source CS-17",
        calibration_id="CERT-2026-1042",
    ),
    limits=AcceptanceLimits(
        minimum_current_a=0.98,
        maximum_current_a=1.02,
        maximum_absolute_bias_a=0.01,
        maximum_relative_error_percent=1.0,
        maximum_standard_deviation_a=0.005,
        maximum_start_lateness_seconds=0.02,
        maximum_acquisition_duration_seconds=0.2,
    ),
)

evaluated = framework.run_evaluated_test("greenlee", policy=policy)
print(evaluated.verdict.status.value)
```

`evaluate_result()` evaluates existing analyzed evidence without another device
read. `evaluate_archived_result()` is read-only and links its verdict to the
source UUID. Verdicts are derived artifacts rather than changes to the Phase 5
archive, so the same evidence can be re-evaluated under a newer policy version.

All comparisons are inclusive (`>=` for the configured lower current bound and
`<=` for upper bounds) and use unrounded values. A valid limit violation is
`FAIL`. Invalid configuration, acquisition failure, corrupt/inconsistent
evidence, or unsafe arithmetic raises a typed error and produces no verdict.

## Assess historical performance consistency

Persist a stable operating-point identity with every run selected for one
historical series:

```python
from src.testing.archive_models import RunMetadata

metadata = RunMetadata(
    test_name="one_ampere_stability",
    dut_id="DUT-001",
    station_id="ATE-01",
    attributes=(("consistency_group", "one-ampere-bench-v1"),),
)

# Acquire and archive at least three like-for-like runs over time.
assessment = framework.assess_archived_consistency(
    (run_id_1, run_id_2, run_id_3),
)

print(assessment.metrics.run_to_run_standard_deviation_a)
print(assessment.metrics.trend_slope_a_per_hour)
```

Phase 8 reports:

- mean, minimum, maximum, and peak-to-peak spread of run means;
- population standard deviation of run means;
- maximum absolute change between chronologically adjacent run means;
- arithmetic mean and pooled RMS of within-run population deviations;
- run-to-run coefficient of variation when the mean is nonzero;
- least-squares current trend in amperes per hour and its fitted change across
  the complete series.

Runs are sorted by sampling completion time, not archive insertion order. The
trend therefore assumes the station UTC clock is trustworthy. These metrics
describe stability of successful like-for-like runs; they do not prove accuracy,
calibration validity, or operational failure rate. No PASS/FAIL threshold is
invented—Phase 7 remains the explicit policy-driven verdict layer.

## Sampling semantics

The Phase 3 scheduler has explicit, testable behavior:

- `sampling_frequency_hz` is required and must be positive and finite.
- At least one of `measurements_count` or `total_duration_seconds` is required.
- The first measurement is scheduled immediately at offset zero.
- Later targets are anchored to `start + index / frequency`; measurement latency
  therefore does not accumulate as timing drift.
- Duration is a half-open start window. A measurement is not started at or after
  the deadline, but a request already in flight is allowed to complete.
- Reads remain serialized. If acquisition is slower than the requested period,
  the next read starts as soon as possible and its lateness is recorded.
- Device and sleep failures stop the run immediately and propagate unchanged.

Python on a desktop OS is not a hard real-time system. Here, precise timing means
monotonic, drift-resistant scheduling plus recorded timing evidence for every
sample.

## Configuration

`config/config.yaml` is the source of truth for endpoints, commands, timeouts,
the default sampling plan, optional acceptance policy, and result archive:

```yaml
testing:
  sampling:
    measurements_count: 5
    total_duration_seconds: null
    sampling_frequency_hz: 5.0
  acceptance:
    policy_name: "bench-current"
    policy_version: "2026.1"
    reference:
      current_a: 1.0
      source: "calibrated current source CS-17"
      expanded_uncertainty_a: 0.001
      calibration_id: "CERT-2026-1042"
    limits:
      minimum_current_a: 0.98
      maximum_current_a: 1.02
      maximum_absolute_bias_a: 0.01
      maximum_relative_error_percent: 1.0
      maximum_standard_deviation_a: 0.005
      maximum_start_lateness_seconds: 0.02
      maximum_acquisition_duration_seconds: 0.2
    ammeter_overrides:
      entes:
        limits:
          maximum_standard_deviation_a: 0.003

result_management:
  archive_directory: "../results"

analysis:
  visualization:
    enabled: true
    plot_types: [run_overview, accuracy, consistency]
    output_directory: "../plots"
    image_format: "png"
    dpi: 160

emulation:
  fault_injection:
    enabled: false
    ammeters: {}
```

Relative archive paths are resolved against the YAML file's directory.
Configuration loading is read-only; the directory is created only on the first
successful save.

Relative visualization output paths follow the same rule. Enabling defaults
requires at least one supported plot type and an output directory. The checked-in
configuration keeps automatic output disabled; an explicit CLI `--output`
remains usable.

Fault injection is also opt-in. When enabled, it requires at least one known
configured ammeter with a nonempty, uniquely numbered schedule. Unsupported
keys, hidden rules under `enabled: false`, and fault parameters that do not
match their type are rejected while loading YAML.

Set either count, duration, or both. A configured plan always requires frequency.
If all three values are `null`, no default plan is created and `run_test()` must
receive an explicit `SamplingPlan`.

Acceptance limits are optional individually, but every resolved policy enables
at least one. An ammeter override inherits global limits and may replace or
disable individual limits with YAML `null`. A supplied override `reference`
replaces the complete global reference. Bias limits require a reference, and a
relative-error limit additionally requires a nonzero reference current.

| Ammeter | Host | Port | Command |
|---|---|---:|---|
| Greenlee | `127.0.0.1` | 5000 | `MEASURE_GREENLEE -get_measurement` |
| ENTES | `127.0.0.1` | 5001 | `MEASURE_ENTES -get_data` |
| CIRCUTOR | `127.0.0.1` | 5002 | `MEASURE_CIRCUTOR -get_measurement` |

Commands and responses are newline-delimited on the wire. A successful response
contains one finite floating-point value in amperes. Protocol failures use an
explicit `ERROR <message>` response.

## Architecture

```text
YAML configuration
    -> AmmeterFactory / AmmeterRegistry
    -> AmmeterTestFramework.run_test()
    -> SamplingRunner (absolute monotonic deadlines)
    -> SocketAmmeter.read_current()
    -> SocketTransport
    -> SampledMeasurement records
    -> SamplingRunResult
    -> ResultAnalyzer (mean / median / population std dev / min / max)
    -> CurrentStatistics
    -> AnalyzedSamplingResult
    -> JsonResultArchive (schema / checksum / atomic write)
    -> general/<run UUID>.json OR grouped assessment/<run UUID>.json
    -> load / list / filter / compare
    -> compatible archived cohort + ReferenceCurrent
    -> AccuracyAssessor (bias / precision / RMSE / pairwise agreement)
    -> ReferenceAccuracyAssessment -> JSON or plain-text report
    -> AcceptancePolicy (YAML default plus optional ammeter override)
    -> ResultEvaluator (range / bias / precision / timing checks)
    -> AcceptanceVerdict -> JSON or plain-text PASS/FAIL report
    -> compatible same-ammeter archive series + consistency_group
    -> HistoricalConsistencyAnalyzer (repeatability / spread / drift)
    -> HistoricalConsistencyAssessment -> JSON or plain-text report
    -> ResultVisualizer (object-oriented Matplotlib + Agg canvas)
    -> non-overwriting PNG / SVG / PDF artifact
    -> optional FaultProfile at emulator protocol boundary
    -> typed timeout / protocol error OR valid offset evidence
```

All three instruments currently use the same wire protocol, so one adapter is
configured with a different name, endpoint, and command for each device. A
vendor-specific adapter can be added later if behavior genuinely differs.

## Run the tests

The suite uses the standard-library `unittest` runner and is compatible with
pytest:

```shell
python -m unittest discover -s tests -v
```

Tests use deterministic injected clocks/fakes or operating-system-assigned
loopback ports. They require no physical hardware and no external network.

## Project structure

```text
Ammeters/                 Emulator physics/lifecycle and compatibility client
Ammeters/faults.py        Immutable deterministic emulator fault schedules
config/config.yaml        Devices, sampling, acceptance, archive, plots, faults
config/fault-scenario.example.yaml  Runnable three-ammeter overcurrent scenario
docs/                     Design, traceability, sample results, interview guide
examples/                 Runnable demo, assessment, and visualization CLIs
src/devices/              Contracts, record, transport, adapter, factory, registry
src/testing/models.py     Immutable sampling, timing, and analysis records
src/testing/sampling.py   Drift-resistant synchronous scheduler
src/testing/analysis.py   Pure standard-library statistical analysis
src/testing/archive*.py   Archive models, strict codec, and JSON repository
src/testing/accuracy*.py  Reference assessment models and pure calculations
src/testing/acceptance*.py  Versioned limits and pure PASS/FAIL evaluation
src/testing/consistency*.py  Historical repeatability and drift assessment
src/testing/visualization.py  Headless run/accuracy/consistency rendering
src/testing/reporting.py  Deterministic human-readable result reporting
src/testing/test_framework.py  Additive execution/analysis/archive/verdict facade
src/utils/config.py       YAML loading and validated configuration models
tests/                    Hardware-free unit and loopback integration tests
main.py                   Local-emulator orchestration helpers and one-shot CLI
```

All required features and all specified bonus challenges are now implemented.
Visualization stays at the presentation boundary, and fault injection stays at
the emulator boundary, so neither changes production-style client, sampling,
analysis, verdict, or archive semantics when disabled.

## Interview handoff

- [Requirements traceability](docs/requirements-traceability.md) maps every
  supplied requirement to implementation and automated evidence.
- [Representative results](docs/sample-results.md) contains captured output from
  the final real-emulator audit.
- [Interview walkthrough](docs/interview-walkthrough.md) provides a concise demo
  sequence, architectural narrative, tradeoffs, extension points, and limitations.

## Supplied-code corrections

The supplied-code corrections and their rationale are recorded in
`docs/starter-code-fixes.md`. Architectural choices, including the patterns
adapted from the accompanying RF ATE project, are in
`docs/design-decisions.md`.
