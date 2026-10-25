Beta 6 build selection and conservative freeze diagnostics are prepared. See [FREEZE_DIAGNOSTICS.md](FREEZE_DIAGNOSTICS.md) and [BETA6_UPGRADE.md](BETA6_UPGRADE.md) for commands, emergency capture, limitations and validation. No gameplay was launched during this preparation.

Extended intensive gameplay is ready: `python3 profile.py --intensive` (300 seconds, optional `--intensive-seconds 600`). Spoken cues, lightweight logging, 120-second recovery, threshold episodes and optional separately selected Overview trace reuse the recovery workflow. See [RECOVERY_GUIDE.md](RECOVERY_GUIDE.md).

Targeted transition/combat recovery preparation is available via `--recovery screen-transition` / `--recovery combat`; see [RECOVERY_GUIDE.md](RECOVERY_GUIDE.md). Planned events are retained and each recovery lasts 120 seconds. Existing modes below remain available.

Dynamic resolution is now the primary investigation. For the first low-overhead session:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --dynamic key-cavern
```

See **DYNAMIC_GUIDE.md** for 30-second warm-up + three 60-second phases, optional Goponga
and fixed 1x controls, what to share, and focused tracing only after an anomaly. See
**DYNAMIC_REVIEW.md** for the unchanged controller/pacer/MetalFX review. The original
fixed-resolution Instruments workflow below remains available and tested.

# LASRecomp M1 profiling preparation

First gameplay session, in **macOS Terminal** (run this later, when ready to play):

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py
```

No download, working-directory assumption, shell heredoc, installation, build, or sudo is needed.
The default is **Scenario A / baseline / stationary / Game Performance Overview / 25 seconds**.
It asks you to type LAUNCH, then READY after reaching the room. Return to the game within
10 seconds; it warms up for 30 more seconds and records automatically. Quit normally when
it beeps. The command waits for game exit, checks trace target identity, and prints the
shareable ZIP path. Use CAPTURE_GUIDE.md for the exact scene/settings procedure.

To check prerequisites without starting the game or copying saves:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --dry-run
```

Successful preparation is not a successful gameplay capture. No LAS Recomp session was
launched during preparation. Synthetic tool attachment and capture worked on this Mac;
real gameplay attachment, rendering state, timing rows and complete frame coverage remain
unverified. See VALIDATION.md and AUDIT_FIXES.md.

## Optional separately labeled sessions

Append one option set to the same command:

| Purpose | Options |
|---|---|
| A, focused 8-second Metal System Trace | `--method metal` |
| A, longer initial shader-cache warm-up | `--warmup 120` |
| B, Key Cavern internal 1x, same Retina drawable | `--scenario B` |
| C, Goponga stationary, Retina Match | `--scenario C` |
| C, separately labeled movement | `--scenario C --motion movement` |
| Partial GPU command-buffer capture, intrusive | `--method frame` |

`--method frame` enables `MTL_CAPTURE_ENABLED=1` only for that separately labeled run.
Despite the short option name, it captures **one command buffer**, not a certified full
frame. This is a documented limitation, not a full-frame workflow proven for LAS Recomp.
Overview/Metal timeline runs do not enable that layer. All sessions keep no-FS disabled.
No experimental-renderer launcher is provided in this preparation task.

## What preflight checks

- Exact `~/Developer/LASRecomp/build/lasrecomp`, executable and not a symlink; no app fallback.
- Existing extracted content and compiled library. NSO build ID, sidecar library ID and
  generator ID embedded in the executable must agree. This is a static compatibility
  check; library ABI loading remains a gameplay-dependent check.
- Executable/library SHA-256, Git branch/HEAD/dirty paths, pinned bundled-isolation hash.
  The runtime loaded-library banner must match the hashed library before recording.
- Installed Xcode, Instruments templates and command-line utilities, free storage
  (at least 10 GiB), and conflicting `lasrecomp` processes. Permission-denied checks fail
  clearly rather than assuming no process exists.
- Hardware, power/Low Power Mode, thermal state and display mode where available.
  `tool-probe` is the locally compiled, asset-free metadata helper. Its source is included;
  missing helper information is marked unavailable.

Input discovery ignores inherited disposable data/settings/save overrides; use explicit
`--data-root`, `--settings`, `--save-dir` only when intentionally selecting existing inputs.

Instruments uses per-command DEVELOPER_DIR. No global developer-directory or permission
settings are changed. macOS may request recording permission on the first Terminal run;
if it fails, preserve the local error and use Instruments' normal UI permission guidance.
Do not disable system security or change performance settings to get a recording.

## Protection and outputs

Each unique UTC session folder is under:

`~/Developer/LASRecomp-Metal-Research/profiling/sessions/`

Names include date/time, A/B/C scenario, baseline, 2880x1800, method, motion and random ID.

- `private/`: private save/settings copies, home-pointer directory, temporary files and
  empty caches; never automatically deleted, even after normal exit. The data overlay
  references existing extracted content/fonts read-only by the runtime, with no extraction
  or launcher/setup path enabled. This is application-level isolation, not OS enforcement
  of read-only original files. The original source checkout is never used as working directory.
- `runtime-local.log`, `manifest-local.json`, recorder log, optional `toc-local.xml` and
  `.trace` / `.gputrace`: **local only**, may contain paths, resources, environment and game data.
- `safe-summary.zip`: only fixed-field metadata, numeric measurements, fixed error codes,
  instructions, and optional sanitized analysis. This is the only gameplay file to share.
  No raw logs, raw XML, traces, captures, settings, saves or game code are included.

The launcher strips inherited experiment/debug environments, including presence-based
flags: setting those flags to `0` is insufficient for some runtime checks. Baseline flags
are only `LARECOMP_DEPTH_NO_FS=0`, no-launcher safety, and private data/settings/save/library
paths. Default periodic FPS/renderer stats, scale-change logs and occasional allocation
logs remain. Their overhead is unquantified; no per-draw observer, pace trace or depth probe
is enabled. Private cold caches can require a longer warm-up than historical sessions.

Ctrl-C stops an active recorder and waits for you to quit the game normally. It never
kills the game or deletes private files. A crash/closed Terminal also leaves private files
available. Do not delete `private/` while its PID is alive. After normal exit you may manually
remove an entire unwanted session; no cleanup command is run automatically.

## Reproducible package setup (stdlib only)

Extract the whole review ZIP into an empty folder; retain all neighboring files. No pip,
external isolation helper, downloads or original checkout are needed for mocked tests.
`isolation.py` contains the narrow copy/discovery implementation; `DEPENDENCIES.json`
pins all runtime/test source hashes and its origin/version. Do not regenerate this manifest
just to bypass a mismatch; restore the reviewed files or intentionally revalidate changes.

```sh
python3 /absolute/path/to/extracted/setup_check.py
python3 /absolute/path/to/extracted/setup_check.py --fixture-dry-run
```

The first verifies dependencies; the second runs fixture-only mocked preflight/isolation,
never actual game data or real tools. A real `profile.py --dry-run` additionally needs the
existing macOS/Xcode/game installation. An absent optional `tool-probe` only makes GPU/
display/thermal metadata unavailable. To rebuild that asset-free metadata helper locally:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun clang -O2 -Wall -Wextra -Werror -fobjc-arc -framework Foundation -framework Metal -framework CoreGraphics /absolute/path/to/extracted/tool_probe.m -o /absolute/path/to/extracted/tool-probe
```

Shared metadata is recursively allowlisted, including enum-normalized settings. Branch
names (only accepted bounded project prefixes), timestamps, build/library/dependency
hashes and fixed scene labels are intentionally shared. Unknown strings/fields are
unverified/removed. Raw process logs, error stacks, XML, traces, saves and settings stay local.
Failed analysis produces `analysis-error.zip` while preserving a prior safe-summary.zip.
ZIP replacement completes and verifies before replacing the prior archive.

Non-gameplay tests (59 retained + 52 audit + 4 recovery regressions; use only synthetic temporary saves):

```sh
cd ~/Developer/LASRecomp-Metal-Research/profiling
python3 -B -m unittest -v test_profiling test_audit test_dynamic
```

Analysis options are documented in ANALYSIS_PLAN.md. Raw capture tools can be intrusive;
compare only the same scene/settings and capture method. Do not pool resolutions/scenes.

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
