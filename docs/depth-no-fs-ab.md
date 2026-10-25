# Opt-in depth omission: sample and equivalent-view correction

The default renderer still executes fragment shaders. `LARECOMP_DEPTH_NO_FS=1` now accepts raw NVN sample counts
zero or one **only** with an actual single-sample Metal attachment and the existing single-sample pipeline.
It accepts a declared depth view only after proving it equivalent to the full base 2D attachment. No stencil,
discard, coverage, shader-side-effect, synchronization, storage-snapshot, or pipeline-cache guard is removed.

## Evidence and implementation

`objects.c:nvnTextureBuilderSetDefaults` zeroes samples; `texture_from_builder` copies the raw value unchanged.
`metal.m:create_backend_texture` sets `sampleCount` only above one; otherwise Metal's 2D descriptor stays at one.
`renderer.m:rec_from_state` already normalizes raw zero/one to one. For zero declared color slots,
`attachment_formats` leaves the pipeline sample count at its default one. The correction reads the actual pass
descriptor before selection and requires agreement; unknown counts and any multisampling remain rejected.

`NvnTextureView.setmask` declares levels (1), layers (2), format (4), swizzle (8), depth/stencil mode (16) and
target (32). The shared `depth_attachment.h` proof requires every declared field to match the base, including
base mip/layer zero and the full remaining range (a count of zero means remaining). Unknown mask bits, subset or
shifted ranges, format aliases, altered swizzles/modes/targets, arrays and missing metadata remain excluded.
`view_texture` selection is unchanged. An optional out parameter returns the base it already resolved, avoiding
another texture-cache lookup. The actual attached Metal object must equal that base, match its expected depth
format, and use level/slice/depthPlane zero; any stencil attachment must agree. A failed view returning its base
cannot admit a nonidentity declaration because both declaration and actual attachment are checked.

The pass proof is observed once on pass creation when the experiment or diagnostics are enabled. The opt-in
selector uses that proof; diagnostics do not authorize draws. `depth_no_fs.h`, pipeline hashes/keys/descriptors,
preparation of both forms, fallback behavior, feedback resolution, storage snapshots and pacing are unchanged.
Diagnostics schema 2 adds `potential_view_equivalent` and `potential_safe`: intersections with the probe-potential
subset. `potential_safe` evaluates the same guards with the switch hypothetically enabled **for counting only**,
so default A and experimental B can report opportunity without changing A. `depth_view` now means unproven or
nonidentity attachment semantics; `samples_unknown` means absent/mismatched effective single-sample evidence.

The old mixed-resolution recording had 1,580,465 probe-potential draws. Stencil first rejected 709,523;
at most 870,942 (55.1% of potential; 16.0% of all completed draws) could remain after both corrections.
This was an upper bound, not a safety certificate or GPU savings estimate. Do not use its aggregate FPS as A/B data.

## Completed validation and observed gameplay

The saved October 24 validation (`LASRecomp-Validation-20261024-173913.zip` on Desktop) records:

| Check | Result |
| --- | --- |
| Host-only build | exit 0; no game-code generation |
| Attachment proof under ASan/UBSan | 352 checks |
| Existing fragment eligibility | 107 checks |
| Diagnostic accounting/equivalence | 196,748 checks, including 98,304 guard combinations |
| Depth probe / pacing / Dynamic resolution | 30 / 9 / 23 cases |
| Standalone Apple M1 Metal | 384 depth/stencil comparisons; ASan/UBSan-built executable |

Metal tests cover raw zero/one; absent, empty and explicit full-range views; one/three mip levels;
Depth16Unorm, Depth32Float and Depth32Float_Stencil8; all eight compare modes; depth bias, overlapping geometry,
scissor and untouched-mip sentinels. They compare depth and stencil readback bit-for-bit, keep stencil disabled,
and reject real shifted attachment/view witnesses. They do not establish arbitrary in-game visual correctness.
Previous diagnostic-stage shader tests passed 34 instruction cases and 4,000 MSL comparisons; translator source
has not changed in this correction. Vulkan/SPIR-V validation was not performed (`glslc` unavailable at that stage).

The existing paired ZIP `LASRecomp-M1-AB-20261024-183122.zip` confirms activation at 2880×1800:

| Reported measurement | Default | Experimental |
| --- | --- | --- |
| Completed draws (reported intervals) | 632,067 | 615,847 |
| Probe potential / safe opportunity | 149,914 / 82,143 | 143,986 / 78,229 |
| Actual omissions | 0 | 78,229 |
| Pending / failed / fallback / inconsistent | all 0 | all 0 |
| Warmed Key Cavern FPS median | 30 | 30 |
| Interval GPU/present proxy median | 29.75 ms (23 samples) | 29.44 ms (22 samples) |

All experimental potential views in that recording were equivalent; stencil excluded 65,757 potential draws.
53 prepared experimental pipelines succeeded; no live experimental builds were requested. The roughly 1% proxy
difference is inconclusive: short asynchronous samples and manual routes do not establish a repeatable GPU benefit.
The user reports no visible defects. This is initial human validation, not an exhaustive visual regression pass.
The older collector's expected-experiment/drawable warnings were hardcoded assumptions, not renderer failures.

## Controlled manual A/B

```sh
python3 -B ~/Developer/LASRecomp/tools/depth_no_fs_ab.py
```

The helper defaults to the latest tested 2880×1800 drawable. For a separately chosen reduced macOS display mode,
append `--drawable 2048x1280`. Do not change macOS display settings between A and B. The helper never changes them.
Use identical power/background-work conditions, the same Key Cavern room and repeatable route. It launches the
existing development binary only after each explicit prompt. Independent private copies of the same source saves
and preferences protect originals; private preferences set fullscreen, Original 16:9, Match and AA Off, retaining
the same upscaler. Other inherited `LARECOMP_*` hooks are cleared; preparation, pacing and synchronization stay on.

Warm up at least 30 seconds in the room, return to Terminal to arm, then refocus within ten seconds. Follow the route
for the 120-second window, then quit normally after the terminal bell. Inspect flickering, dark rectangles, missing
geometry and depth artifacts in both runs; explicitly report the result. No gameplay input or timed termination is
automated. Do not import/rebuild game code, switch seeds, or change the data directory during collection.

Separate `A-default` and `B-experimental` directories retain complete child `run.log`, bounded `measurement.log`
and `summary.json`. The first straddling and final partial diagnostic intervals are excluded. Timing excludes ten
seconds after the first measured level sample. Settings snapshots plus change-triggered `[scale]` lines flag
observed configuration drift, including Match → 1x → Match scale changes. Six-second settings snapshots cannot
prove that a very brief unrelated setting change never occurred; leave settings untouched throughout.

Missing instrumentation, boundary/accounting errors, insufficient Key Cavern samples, shader compilation, pipeline
fallback/problems, a settings/output mismatch, nonzero process exit or incomplete visual checking invalidate the
comparison. `COMPARISON.md` prints a timing difference only for a valid pair. GPU totals are asynchronous proxies,
not exact per-frame percentiles. Repeat after cooling with `--reverse` to check order/thermal effects.

The Desktop ZIP contains only allowlisted logs/JSON/Markdown, never private saves/preferences, binaries, shader
source or game files. Finder highlights the final ZIP. Runtime logs may include ordinary local paths; review before
sharing. The new helper has 14 synthetic tests (including successful/failed two-run collection and Finder calls);
the existing collector's 15 tests still pass. Neither helper was used to launch gameplay by this agent.

## Remaining decision

Nonzero omissions are established; meaningful M1 GPU improvement remains unproven. Retain all safety guards and
the opt-in default until repeatable warmed GPU savings and broader visual coverage justify more work. The ordinary
pacer release requires GPU average below 15 ms, with stricter 13/10 ms limits for late-frame holds/backoff and
additional CPU/stability requirements. A 29.44 ms proxy still needs about 14.44 ms (49%) reduction to reach 15 ms;
draw-count ratios do not predict such a gain. Do not change pacing to manufacture a 60 FPS result.

A separate asset-free synthetic Metal benchmark is the next research step: isolate attachment resolution,
overdraw, fragment cost and store/load bandwidth, with measured command-buffer timing and correctness checks.
It has not been started here. No commit, push, rebase, merge or PR is authorized by the latest user instruction.
