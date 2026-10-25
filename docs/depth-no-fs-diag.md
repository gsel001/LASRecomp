# M1 Metal depth omission: rejection investigation

This is the historical instrumentation report for `0be6fb2`. The later sample/view proof, activated gameplay
results and fixed-Match A/B helper are documented in [depth-no-fs-ab.md](depth-no-fs-ab.md).

This change instruments the existing opt-in experiment. It does **not** relax eligibility or change shader text,
pipeline selection, texture allocation, storage snapshots, CPU/GPU overlap, synchronization, frame pacing, Dynamic
resolution, or gameplay. The default renderer remains the default. No in-game visual verification or speedup is claimed.

## Findings before collecting the new diagnostics

The valid experimental process capture from the second October 24 A/B run contains `experimental=1`, 14 reported
intervals, 1,743,857 completed NVN draw commands, zero omissions, and zero experimental pipeline fallback attempts.
Its scale line reports a 2048×1280 drawable. It contains no pipeline/translation/compile failure messages. The separate
installed-app log is not evidence for that development process. These observations confirm activation and lack of a
measured omission benefit; they do not identify the particular failed guard.

**The strongest source-level hypothesis is a sample-count representation mismatch.**

- `nvnTextureBuilderSetDefaults` in `runtime/nvn/objects.c` zeroes the sample field. `texture_from_builder` copies it
  unchanged to `NvnTexture.samples`.
- `create_backend_texture` in `runtime/nvn/metal.m` sets Metal's `sampleCount` only when the raw count exceeds one;
  the ordinary 2D texture descriptor otherwise stays single-sampled.
- `rec_from_state` in `runtime/nvn/renderer.m` starts with `samples=1`, overriding it only for raw counts greater than
  one. Shader preparation therefore uses a normalized count.
- `depth_no_fs_draw`, in contrast, passes the raw texture count to `depth_no_fs_eligible`, which requires exactly one.
  Raw zero is rejected even when the actual Metal depth attachment has one sample. The probe uses Metal's actual count.

This is a confirmed inconsistency in representation, and a plausible explanation of probe candidates disappearing
before pipeline selection. **Whether it accounts for the tested Key Cavern draws remains unmeasured.** The new
`raw0_metal1` and `potential_raw0_metal1` counters directly test that hypothesis. The restrictive guard is unchanged.

Other hypotheses remain: any depth view (including a possibly identity view), stencil enable, depth test/write
state, bound images, or an unsupported shader-header certificate requirement. Nonzero declared color-slot counts
can reject a pass with no actual color attachments, but all 208 shipped graphics variant records having depth and
no nonzero color format have zero declared color slots, one sample, and triangle topology. That makes declared slots
a weaker explanation for those prepared variants; it does not prove the live scene uses only those variants.

Zero fallback attempts makes eligibility rejection a stronger explanation than an unavailable experimental pipeline.
It does not logically rule out eligible attempts skipped later in the draw. The new pre/post accounting measures that.
Cache hashes, descriptor fragment-function identities, preparation of both forms, and fallback behavior remain intact.

Upstream was checked through `95404dc` on `beta_6`. Since the WIP's upstream base `7952364`, the only renderer change
is Vulkan recorder handling for ARM Mali drivers (`016bbd6`); there is no duplicate Metal optimization to adopt here.
The local development branch and prior WIP history were preserved.

## Changed files

| File | Purpose |
| --- | --- |
| `runtime/nvn/depth_no_fs_diag.h` | Pure C observation/classification, mutually exclusive rejection counts, secondary overlapping counts and formatting. |
| `runtime/nvn/renderer.m` | Observe live state and completed/skipped draws; count translation/build events and report aggregates. Existing selectors/cache functions remain unchanged. |
| `runtime/nvn/metal.m` | Read-only periodic snapshots of actual output dimensions, scale and graphics settings. |
| `runtime/nvn/maxwell/shader.h` | Append a diagnostic-only certificate-explanation bitset. |
| `runtime/nvn/maxwell/translate.c` | Populate explanations once, including separately decoded fragment stores; emitted shaders and legacy eligibility flags remain unchanged. |
| `Makefile` | Include the new header in the translator cache/dependency identity. |
| `tools/depth_no_fs_diagnostic.py` | One-command manual collector, private settings/saves, log analysis, safe ZIP allowlist and Finder reveal. |
| `tools/test_depth_no_fs.c` | Extend real-translator tests to verify recorded diagnostic explanations. |
| `tools/test_depth_no_fs_diag.c` | Guard equivalence, first-failure/overlap accounting, sample-pair counters and formatting. |
| `tools/test_depth_no_fs_diag.py` | Compile/run those focused tests with ASan/UBSan. |
| `tools/test_depth_no_fs_collection.py` | Test analysis, missing-data warnings, successful/failed synthetic child collection and original-data protection. |
| `tools/test_translate.sh` | Preserve reference headers' relative include paths for existing translator regression comparisons. |
| `docs/depth-probe.md` | Correct development-process logging guidance and distinguish the original opportunity count from eligibility. |
| `docs/depth-no-fs-diag.md` | Investigation evidence, counter definitions, validation, collection instructions and remaining risks. |

## Switches and reporting

`LARECOMP_DEPTH_NO_FS_DIAG=1` enables the new observer. Other values/unset disable its counters and log output.
`LARECOMP_DEPTH_NO_FS=1` independently enables the existing experimental selector. Diagnostics alone never enable it.
`LARECOMP_DEPTH_PROBE=1` independently enables the previous probe and target-size grouping.

There is no allocation, file I/O, logging, clock read, or atomic operation in the observer's per-draw accounting.
It reads existing state/metadata and updates bounded render-thread counters. Translation explanations are computed
once per translated shader. Atomic event counters cover infrequent pipeline builds and translations on worker threads.
Reports use the existing statistics points, at least five seconds apart (normally about six seconds). Output settings
snapshots have a six-second minimum interval. No per-draw or per-shader log is emitted.

Illustrative numbers only:

```text
[depth-no-fs-diag] frame 900 interval 6.0s attempts=10002 evaluated=10000 eligible_evaluated=0 total=10000 depth_bound=8000 depth_only=3000 probe_potential=2900 entered=10000 certified=9000 eligible=0 omitted=0 raw0_metal1=3000 potential_raw0_metal1=2900
[depth-no-fs-diag] rejected(first; completed draws): color_bound=7000 depth_view=3000
[depth-no-fs-diag] probe_potential_rejected(first; subset of completed draws): depth_view=2900
[depth-no-fs-diag] depth_only_reasons(overlap): depth_view=3000 samples_unknown=3000 discard=100
[depth-no-fs-diag] pipeline(interval encounters): pending=0 failed=0 fallback=0 inconsistent=0
```

The overlapping line matters: if both sample count and view restrictions block the same draws, changing just one
would still leave zero omissions. A first-failure tally alone cannot establish that removing one condition would help.

## Counter definitions and accounting

All interval draw counters count completed **NVN draw commands**, not pixels, instances, or individual Metal draws.
Clear/copy helper draws, compute dispatches, and shader preparation are not in that denominator.

| Field | Denominator / definition |
| --- | --- |
| `attempts` | Calls to the NVN draw executor, including skipped commands. |
| `evaluated` | Attempts reaching the existing omission selector before pipeline lookup. |
| `eligible_evaluated` | Evaluated attempts for which the actual selector returned true, including later skips. |
| `total` | Completed commands, at the existing `stat_draws++` site. |
| `depth_bound` | Completed commands with a depth/stencil texture object bound (even if its format is unsupported). |
| `depth_only` | Completed commands with a depth-capable, non-stencil-only attachment and no actual color texture. |
| `probe_potential` | `depth_only` commands passing the unchanged probe classification, using actual Metal dimensions/samples. |
| `entered` | Completed commands evaluated while the experimental switch was on. |
| `certified` | Completed commands whose fragment metadata has the existing MSL certificate, regardless of render state. |
| `eligible` | Completed commands initially selected by the actual live eligibility helper, before pipeline fallback. |
| `omitted` | Completed commands that ultimately used the experimental pipeline, after fallback handling. |
| `raw0_metal1` | `depth_only` commands with raw NVN sample count zero and actual Metal sample count one. |
| `potential_raw0_metal1` | The intersection of `probe_potential` with that raw-zero/Metal-one condition. |

Primary rejection counters are mutually exclusive. The first set reason in the documented enum order is counted
once per rejected completed command. All zero entries are omitted from the log; `none` means zero rejections.

```text
total = eligible + sum(rejected(first))
attempts = evaluated + pre_no_program + pre_program_not_ready + pre_other
evaluated = total + post_pipeline + post_other
omitted <= eligible <= total
potential_raw0_metal1 <= probe_potential <= depth_only <= depth_bound <= total
```

`probe_potential_rejected(first)` repeats the first-failure classification for the probe-potential subset. Its sum
plus eligible commands within that subset equals `probe_potential` (the latter intersection is not separately logged).
`depth_only_reasons(overlap)` counts every blocking reason on depth-only commands; its sum must not be treated as
the number of rejected draws. `inconsistent` reports observer/selector disagreement or an omission without initial
eligibility. The observer never overrides the selector. Primary accounting uses the actual selector's result.

The skipped line's `pre_program` subsets are observational: failed programs can be hidden by `get_program` returning
nil, so draw-level metadata cannot always identify their particular translation failure. The cumulative translation
event counters below expose those failures when the original metadata is still available. `pre_other` covers existing
debug/hash and item-twinkle skips; `post_other` covers existing item-cursor and unsupported-primitive skips.

### First-failure order and secondary reasons

| Reasons, in priority order | Actual source restriction |
| --- | --- |
| `switch_off` | Existing experiment not enabled. |
| `depth_missing`, `depth_format` | No texture, non-depth format, or stencil-only format. |
| `color_bound` | Any actual color texture in the declared slots. A write mask of zero does not bypass this. |
| `depth_test_off`, `depth_write_off`, `stencil`, `alpha_to_coverage` | Existing depth/stencil and multisample state bytes. |
| `depth_target`, `depth_view`, `color_declared`, `depth_compare`, `depth_test_env_off`, `image_bound`, `topology` | The individual restrictions currently combined in `DepthNoFsState.unknown`. A nonzero declared slot count is distinct from actual color binding. |
| `samples_unknown`, `msaa` | Raw NVN count zero, or nonzero count other than one. `samples_unknown` describes the strict guard; it does not claim Metal's actual count is unknown. |
| `shader_missing`, `instruction_unknown`, `shader_unknown` | Missing metadata, a translation error explicitly naming unsupported/unknown instructions, or another existing probe metadata rejection. |
| `discard`, `depth_output`, `coverage` | Existing discard/depth flags and SPH depth/sample-mask outputs. |
| `gmem_write`, `gmem_read_or_untyped`, `image_resource`, `other_shader_effect` | Stores, other global-memory access, image metadata, mapped memory or point-size flags. |
| `cert_debug`, `cert_empty`, `cert_output_reserved`, `cert_type`, `cert_version`, `cert_stage`, `cert_kill_header`, `cert_store_header`, `cert_reserved`, `cert_stream` | Every extra requirement of the existing certificate: no debug override, nonempty translation, no SPH output/reserved bits, PS type 2/version 3/pixel stage 5, no declared kills/stores/reserved/stream bits. |
| `cert_unavailable`, `state_unknown`, `inconsistent` | No explainable certificate, an unrecognized unknown-state restriction, or observer drift. |

The certificate follows the [NVIDIA SPH tables](https://nvidia.github.io/open-gpu-doc/Shader-Program-Header/Shader-Program-Header.html).
The type table specifies PS=2; an introductory sentence in that document reverses the type numbers. This diagnostic
change preserves the existing type/version whitelist rather than interpreting that discrepancy as permission to relax it.

**Metadata limitations:** image metadata does not distinguish reads/writes, so all images remain excluded. The MSL
STG translation sets `uses_gmem` but does not set the legacy `uses_gmem_store` flag. The diagnostic now records decoded
fragment STG in a separate explanation field, without changing the legacy flag, emitted code, or eligibility. The
legacy coarse memory exclusion can therefore overlap `gmem_write` as `gmem_read_or_untyped`; it is not proof of a load.
Unsupported atomic instructions are translation failures, not an invented independently supported atomic state.
No general claim about arbitrary shader effects or future instructions is made.

### Pipeline and translation events

`pipeline(interval encounters)` counts attempts, including those that later skip: `pending` is an experimental
pipeline newly queued or still pending after the ready check; `failed` is an encounter with its failed sentinel;
`fallback` is entry into the existing fallback to the normal fragment pipeline. These are not build counts.

`builds(cumulative live/preparation)` counts actual experimental build requests, successful builds, failures, and
outstanding builds. A cache/preparation hit is not a new request. Requests are counted before dispatch; completion
is counted on its worker. At the reported snapshot, `requested = ok + failed + outstanding`. The cumulative counters
survive in-process game resets; do not sum consecutive cumulative lines. `outstanding` means a request without a
completion observed by that report; a worker may finish while the fields are being sampled.

`shader_translations(cumulative)` counts fragment translation events in program creation, not distinct shaders or
draws. `msl_ok` counts successful source generation; `certified` counts existing certificate success.
`shader_cert_rejected(first; cumulative translations)` and `shader_cert_reasons(overlap; cumulative translations)`
explain failed certificates, including failed translations that never reach a draw. Live and prepared program creation
both contribute. Worker snapshots can straddle an in-progress translation; compare settled reports, and do not use
translation counters as draw denominators. No source code, shader bytes or shader identities are logged by this change.

Interval draw counters reset on reporting and game reboot. The final unfinished interval is not flushed at exit.
The collection helper explicitly warns that reported totals exclude that tail.

## One-command manual collection

Run from Terminal after the instrumented host executable has been built:

```sh
python3 -B ~/Developer/LASRecomp/tools/depth_no_fs_diagnostic.py
```

The helper requests macOS 1024×640, fullscreen, Original 16:9, Match display and SMAA Off; it changes none of those
automatically. Press Return to launch `build/lasrecomp`, play the same Key Cavern room/route for about two minutes
after warm-up, and quit normally. It waits for normal exit; it does not warp, script input, take screenshots, or stop
the process on a timer. It refuses to start without an existing compiled game library. If setup requests rebuilding
game code, quit rather than rebuilding during this collection.

It prints the exact executable, source commit and diagnostic switches. Data-root discovery follows the checkout,
configured pointer and existing path overrides; optional `--data-root`, `--settings` and `--save-dir` resolve unusual
setups. It copies settings and the selected vanilla/seed save into private temporary storage, redirects the runtime
to those copies, and deletes them after the child exits. The originals remain untouched. Do not switch seeds or
change the data folder during the run. Other inherited `LARECOMP_*` test hooks are cleared so stale warp/sync/shader
overrides cannot silently influence this session. Normal shader preparation and cache behavior stay enabled.

The timestamped Desktop ZIP contains only `run.log` (this child's complete stdout/stderr), `manifest.json`,
`summary.json`, and `REPORT.md`. Its allowlist excludes saves, settings snapshots, binaries, generated code and assets.
No installed-app log is copied. `open -R` reveals the final ZIP. A failed child still gets its captured logs and warnings.
These local logs can contain normal runtime paths; review them before sharing. Nothing collected is staged by the script.

`[depth-no-fs-diag] output` records actual drawable dimensions, render/allocation scale, source texture size, SDL's
actual fullscreen flag, and runtime aspect/resolution/AA/upscaler values. Aspect `1` is Original, resolution `0` is
Match display, and AA `0` is Off. The script records all snapshots and checks the final one against the request; it
does not infer the logical macOS display mode from drawable pixels. The existing `[scale]` lines are also preserved.
Settings-file values are supporting evidence; runtime snapshots determine what was actually active.

FPS summaries exclude `level -`, ten seconds after each level change, and intervals with present gaps of at least
100 ms. GPU-per-present summaries divide the existing periodic GPU-busy total by that period's presented frames,
and exclude intervals with shader compilation. Per-frame pace GPU deltas are retained separately, excluding explicitly
non-gameplay records. GPU completion timing is asynchronous, so neither statistic is an exact per-frame GPU percentile.
Diagnostic counts can span loads/menus/rooms; correlate raw interval frames with nearby FPS/level records before
attributing them to Key Cavern. Missing instrumentation and accounting discrepancies become warnings, not fake zeros.

## Validation and next decision

Build only the host with `make -j6 build/lasrecomp`; this avoids the generated game-library target. Tests use synthetic
metadata/programs or a standalone Metal device, with no game data:

- `python3 -B tools/test_depth_probe.py` (ASan/UBSan).
- `python3 -B tools/test_depth_no_fs.py` (ASan/UBSan, real translator metadata).
- `python3 -B tools/test_depth_no_fs_diag.py` (ASan/UBSan, guard equivalence and accounting).
- `python3 -B tools/test_depth_no_fs_collection.py` (synthetic logs, fake child processes, scratch-save isolation and ZIP allowlist).
- `tools/test_translate_ops.sh` (existing instruction semantics).
- `REF=32c7f9f GLSL=0 tools/test_translate.sh 4000 4 msl` (unchanged MSL/legacy metadata versus the WIP).
- `python3 -B tools/test_pace.py` and `python3 -B tools/test_dynres.py`.
- Compile `tools/test_depth_no_fs_metal.m` with `clang -fobjc-arc -O1 -g -fsanitize=address,undefined`, link `Metal`
  and `Foundation`, then run its standalone executable with GPU access. It compares depth/stencil readback with and
  without FS across compare modes, bias, scissor, and combined depth/stencil attachments. It is not gameplay validation.

The comparison harness now preserves a reference revision's header include tree; its original layout could not
compile the WIP reference. The historical default reference `652e234` is absent from this checkout, so the available
WIP reference is specified explicitly. Vulkan SPIR-V validation additionally requires `glslc`, which is unavailable;
no tools are installed for this task.

Recorded validation on Apple M1, October 24, 2026:

| Check | Result |
| --- | --- |
| Host build | Passed; 8 existing renderer warnings and 2 existing Metal warnings, no new warnings. |
| Depth probe / eligibility | 30 / 107 checks passed under ASan/UBSan. |
| Diagnostic observer | 196,747 checks passed under ASan/UBSan, including 98,304 combinations of the live guards. |
| Collector | 15 tests passed, including a real synthetic child process, failed-process capture, original-save/settings protection and archive exclusion. |
| Shader instruction semantics | 34 cases, 0 failures. |
| MSL comparison against `32c7f9f` | 4,000 programs, 0 differences; 2,785 translated and 1,215 deliberately invalid inputs rejected by both versions. The MSL-only harness retains its existing unused-variable warning. |
| Standalone Metal / Apple M1 | 32 depth/stencil A/B comparisons passed with an ASan/UBSan-built test executable. GPU access required running outside the sandbox; inside it the test correctly reported no device. |
| Frame pacing / Dynamic resolution | 9 / 23 cases passed. |
| Decision/cache preservation | Existing `depth_no_fs_draw`, `depth_no_fs_prepare`, pipeline hash, descriptor and key functions are byte-identical to the WIP. The eligibility header, pacer, render queue, output-scale controller and slow-frame code are also byte-identical. |

The reference comparison initially failed to compile because its harness omitted relative include dependencies;
that harness issue was fixed before the passing comparison. No final test failure or sanitizer finding remains.
No gameplay was launched. These tests do not establish in-game visual correctness, omission coverage, or GPU benefit.

First inspect `potential_raw0_metal1`, first-failure counts among probe candidates, overlapping blockers, shader
certification failures, and pipeline build/fallback counters. Do not remove a guard solely because it is common.
If normalization is the dominant blocker, a later reviewed experiment can narrowly prove and use the actual
single-sample configuration while preserving all other guards. Views/stencil/resources require their own evidence.

An upstream performance PR still requires nonzero omissions, controlled warmed A/B GPU timings, and human visual
regressions covering shadows, cutouts, floor decals, ambient occlusion, particles, transitions and known overlap flicker.
The 16.82 ms low-display median needs more than 1.82 ms reduction to get below the ordinary pacer's 15 ms release
threshold; a 14.5 ms target needs about 2.32 ms plus tail-latency improvement. At 28.68 ms, normal Retina output needs
more than 13.68 ms to get below 15 ms. No draw-count ratio establishes those savings. Pacer thresholds remain unchanged.
