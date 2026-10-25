Intensive RI runs keep combat/effects/room/screen changes as intended workload. Analyze below-55/45/35 episodes separately (nested thresholds, periodic-block proxies, missing intervals unknown), then compare compile/gap/scale/GPU/pacer timelines. Existing GPU headroom gates differ from the Dynamic budget; do not infer a controller defect from low estimates alone. See RECOVERY_GUIDE.md for optional Overview trigger offsets and trace coverage limits.

Targeted transition/combat recovery preparation is available via `--recovery screen-transition` / `--recovery combat`; see [RECOVERY_GUIDE.md](RECOVERY_GUIDE.md). Planned events are retained and each recovery lasts 120 seconds. Existing modes below remain available.

# Primary focus: unmodified Dynamic baseline

Use DYNAMIC_GUIDE.md and DYNAMIC_REVIEW.md. Analyze DA/DB/DC independently and keep
stationary/movement/recovery separate. Compare DA against optional DC only at the same
scene, camera, route, drawable, MetalFX/AA and power conditions; measure quality (factor
dwell/min/weighted median/max, adjustment/reversal events, recovery/censoring) alongside
sustained periodic FPS, hitch events and controller G/W estimates. No automated Dynamic
versus fixed comparison is delegated to the old fixed-resolution comparator, which correctly
rejects Dynamic state it cannot certify. No scene/route identity is inferred from FPS.

Per-frame p95/p99, exact GPU/stage execution, active texture dimensions, clocks/utilization
and bandwidth remain unavailable unless separately observed. Reversal heuristics do not
prove visible pumping. Floor-over-budget decisions and explicit holds are evidence to
inspect, not sufficient proof of controller failure. Default observation is low overhead;
record a focused Dynamic trace only for a repeatable unexplained condition. If Dynamic
already works well, retain it unchanged. Existing measurement/recovery rules follow.

# Evidence-driven analysis plan

## Inspect quality before performance

Open each local `recording.trace` in Instruments. Match PID to `manifest-local.json` and
verify the stable gameplay interval. Exclude attach/start/stop margins, focus switches,
fullscreen changes, room loads, shader compilation, menus and setting changes. Keep an
invalid interval labeled rather than deleting its evidence. The script's file-offset
window brackets recorder lifetime, not a proven exact stationary trace interval.

Run the local inventory helper after a session:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/analyze.py /absolute/path/to/session
```

It exports the TOC, checks the target PID, and writes a sanitized schema-name inventory
into the safe ZIP. It never shares the raw TOC (which can contain environment values).
Actual installed tables include Overview layer-per-frame/interval/duration metrics and
Metal GPU intervals, submissions and command-buffer/frame assignment. Table presence is
not proof of populated rows, correct units, target attribution or per-frame semantics.
The asset-free helper has no display surface, so successful attachment cannot validate
game presentation metrics. Do not parse arbitrary XML columns into guessed GPU durations.

## Investigate in this order

1. **Game Performance Overview**: select the stable 20–25-second interval; identify available
   CPU/GPU and presentation tracks, missing frames, GPU activity/idle gaps, scheduling,
   thermal/system data. Read the installed track/column explanations. Note power source
   and Low Power Mode. Coarse nominal thermal status does not imply stable clocks.
2. **Metal System Trace**: inspect 5–10 seconds separately at identical settings. Correlate
   CPU submission, queue scheduling, GPU execution, completion, presentation, CPU waits
   and idle gaps. A CPU wait can be synchronization or pacing; it is not proof of saturation.
   Do not sum overlapping intervals/queues as GPU busy time or a frame duration.
3. **GPU capture**: inspect available pass/encoder attachment actions and producer/consumer
   dependencies; confirm actual dimensions and frame coverage. Use counter/replay-derived
   stage/pass measurements only if supported and actually measured. The prepared CLI path
   is a partial one-command-buffer capture; full-frame coverage remains a blocker described
   in CAPTURE_GUIDE.md. A general timeline does not automatically supply per-pass timings.

## Metric meanings

| Metric | Meaning / boundary |
|---|---|
| CPU frame ms | Verified game CPU-frame span; sampled CPU profile is not automatically this |
| GPU execution ms | Target GPU interval with documented attribution; not a CPU wait |
| Present interval ms | Difference between consecutive actual presentation timestamps |
| Pacing decision | Application release/cap/synchronization behavior; not measured shader cost |
| Runtime GPU/present proxy | Asynchronous periodic accounting divided by presented frames; phase mismatch possible |
| Command-buffer GPU ms | Identified buffer GPU end minus start; may overlap other buffers |
| Render-pass GPU ms | Only if a capture/counter tool measures this explicitly; encoder CPU duration is different |

The safe default summary reports runtime periodic FPS and asynchronous GPU/present proxy
median/p95/sample count, skipping the first straddling block. Its percentiles describe
periodic averages, **not per-frame GPU tails**. Exact CPU/GPU/presentation/pass distributions
are explicitly unavailable until their genuine trace series has been identified. No GPU
utilization, bandwidth, clocks or shader invocation counts are fabricated.

## Add selected, genuinely measured numeric series

After identifying actual units and attribution in Instruments (or counter replay), store
an explicit local CSV with **exactly** these columns:

```text
session_id,pid,metric,value,unit,start_s,end_s,source,sample_id,time_s,frame_id
```

Use the real session ID/PID; `unit` must be `ms`; one stable selected interval's bounds in
seconds; `metric` is one of `cpu_frame_ms`, `gpu_execution_ms`, `present_interval_ms`,
`command_buffer_gpu_ms`, `render_pass_gpu_ms`. `source` is `instruments_selection` or
`metal_counter_replay`. Each row is one actual sample. `sample_id` uniquely identifies an observation within
its metric; `time_s` is its actual start timestamp inside the selected interval. Per-frame
metrics require contiguous actual `frame_id` values; missing frame observations fail the
series instead of being padded. For buffer/pass metrics, frame_id may be empty or repeat;
buffer/pass identifiers need not be numeric, and parallel observations may share time_s.
CSV rows must be ordered by timestamp within each metric. Values must be positive/finite.
Overview selection must be at least 20 seconds, Metal at least five; each series needs
at least three observations, coverage within one second of both edges and no gap over
one second. These are completeness gates, not proof of correct metric interpretation. Keep unknown metrics absent.
Manually copied/exported series still require review of their origin and meaning; naming
a column cannot certify it. No sample CSV is included to avoid creating fake evidence.

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/analyze.py /absolute/path/to/session --samples /absolute/path/to/selected-samples.csv
```

The helper rejects mixed sessions/PIDs, units, intervals, invalid values and unsupported
metrics, then reports sample count, median and linearly interpolated p95 per metric. Only
numeric distributions and fixed provenance labels enter the ZIP; raw CSV stays local.

## Future comparisons and conclusions

First compare A versus B with the same scene/camera/route, drawable, upscaler, power
conditions and capture method. Costs decreasing with internal resolution suggest a
resolution-sensitive part of the workload; they do not by themselves prove bandwidth,
fragment cost or texture sampling. Trace passes/counters must corroborate the explanation.
Do not compare C directly as if it were the same scene.

For later baseline/experimental work, obtain authorization for an experimental launcher,
change only the opt-in flag, retain the same binary hash and scene/settings, and repeat
interleaved/reversed session orders. Keep methods/windows identical. After selecting the
same genuine metric source, compare medians/tails with counts and spread; investigate
order/thermal effects and require repeatability. Do not pool settings or proxy and trace
measurements. `analyze.py SESSION --compare OTHER/safe/summary.json --comparison-type resolution`
accepts intended A/Match versus B/1x while holding workload, drawable, executable, library,
method, motion, duration, fullscreen, aspect, AA, dynamic state and upscaler fixed. Observed
scale/derived size must match the intended resolution. `--comparison-type renderer` instead
requires identical resolution/graphics/scenario and only baseline/experimental no-FS flag
changes. `repeatability` (default) requires identical settings/renderer. All require complete,
typed identity/confirmation metadata; legacy summaries missing fields fail rather than
assuming equality. Power/Low Power/thermal differences are explicitly returned for review.
None of these modes authorizes this launcher to enable the experimental renderer. The
comparison checks metadata only;
it does not claim speedup, confirm exact camera position, or implement experimental launch.

Verified synthetic findings remain unchanged: no repeatable no-FS speedup; attachment
choices affect synthetic timings. Compiler elimination, bandwidth, overdraw, other passes
and clocks are hypotheses for gameplay until real GPU evidence identifies costs. High
draw counts or a 30 FPS cap alone cannot establish the bottleneck.

## Failure and privacy behavior after audit fixes

Malformed, missing, incomplete or unexpected TOCs and wrong PIDs fail with fixed codes.
Original XML/stack traces remain local. The main launcher attempts a failure ZIP; analysis
writes a separate `analysis-error.zip` and retains the previous safe ZIP on failure. Both
ZIP writers use verified atomic replacement. Never interpret an old ZIP as a new success
after a failed analysis. Numeric parsing completion is not certification of game performance.

Runtime IDs are periodic cumulative frame counters, so increasing gaps in frame IDs are
normal; duplicate/backward IDs or clocks are invalid. Newly appended warm-up rows must
cover warm-up; recording rows must cover the requested/monotonic recorder lifetime minus
at most four boundary seconds. The first straddling block remains excluded. Runtime
proxies are not aligned to a selected Instruments interval; inspect the trace separately.
No notification listener/start-stop boundary alignment is claimed.

## Analysis retry recovery (independent recheck)

Analysis never rewrites `manifest-local.json` or capture measurements when an input path,
CSV, comparison or current TOC check fails. The original `safe/` files and good ZIP stay
byte-for-byte intact. Original error details remain in `analysis-error-local.txt`;
`analysis-status.json` records the separate sanitized outcome. `analysis-error.zip`
contains capture metadata/measurements unchanged plus the failed analysis result, with
no writes to capture sidecars. A failed TOC check sets `trace_review_required=true`;
a sample/comparison error does not change historical capture validity.

On a corrected retry, the analyzer reads the unchanged capture record and measurements,
adds the successful analysis, atomically replaces the good ZIP and clears the latest
analysis error status. Historical error ZIPs may remain; use `analysis-status.json` to
identify the latest analysis outcome. No renderer, game or capture-procedure changes.

Successful analysis also leaves capture sidecars unchanged. Its new result is in ZIP `analysis.json` and the separate `analysis-status.json`; that status is the latest analysis outcome.
