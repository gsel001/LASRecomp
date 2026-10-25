# First Dynamic session — one command, no Instruments by default

Manually set macOS to **1440×900 scaled**; expect a **2880×1800 Metal drawable**. These
are not the physical panel dimensions. Original 16:9 nominal viewport is 2880×1620.
Close other LAS Recomp copies. Keep power source/Low Power Mode/display fixed; the tools
record conditions but do not change them. Scene navigation is yours, not automated.

Run in macOS Terminal when ready (the agent has not run gameplay):

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --dynamic key-cavern
```

1. Type **LAUNCH**. The existing development executable runs with private settings/saves,
   caches and data overlay, no launcher/import path, and no-FS experiment disabled.
2. In the game select/confirm **Fullscreen · Original 16:9 · Dynamic · MetalFX · AA Off**.
   Enter the same Key Cavern room and approximate camera position used previously.
   Let loading settle before returning to Terminal.
3. Type **READY**, then refocus the game within **10 seconds**. No more Terminal input
   is needed while playing. The automatic timing from READY is approximately:

   | Cue | Time | Action |
   |---|---:|---|
   | Initial period | 0–10 s | Refocus the game |
   | Warm-up | 10–40 s | Stay in the chosen view; at least 30 s |
   | One beep | 40–100 s | Stationary, 60 s |
   | Two beeps | 100–160 s | Repeatable 60 s movement loop, ending at the original position |
   | Three beeps | 160–220 s | Same position/camera, stationary recovery for 60 s |
   | Four beeps | ~220 s | Complete; quit normally |

   Bell audibility depends on Terminal settings; no sound preference is changed. The script
   also prints cues. If bells are inaudible, use a separate timer/stopwatch with this schedule
   rather than switching to Terminal. Actual monotonic phase boundaries are recorded.
4. After quitting, type **CLEAN** only if phase instructions were followed, the same view
   was restored, and no loading/menu/focus/settings changes contaminated the sample.
   Otherwise list affected phase names: `stationary`, `movement`, `recovery`.
5. Visual review: type **NONE** only after checking all below with no defect, **ISSUE** if
   an artifact was observed, or **SKIP** if not checked. Only user reports establish visual
   issues; performance logs do not infer them.

Visual checklist: excessive blur; visible resolution pumping; shimmer; flicker; dark
rectangles; missing textures/objects; incorrect lighting; ghosting/upscale artifacts;
edge clipping; image-quality changes during motion. Note the phase and symptom separately
for your ChatGPT message. An ISSUE retains data but requires review; no automatic fix follows.

If the last warm-up samples are still compiling or stale, quit normally and retry with
`--warmup 120`. Warm-up is not steady-state proof. If recovery is censored or behavior
borderline, repeat after review with `--phase-seconds 120` (six-minute observation) or 180;
some backoff/probe rules exceed one minute. Longer observations help assess fanless sustained
behavior but do not prove thermal throttling or stable clocks.

## Optional scenarios (separate unique folders; same protocol/settings)

- **DB / Goponga:** replace `key-cavern` with `goponga`. Choose water/vegetation and a
  reproducible view, with a loop that returns to it. Location is manually confirmed; only
  a stable non-menu level hash is checked automatically. No claim it is more demanding.
- **DC / fixed 1x:** replace it with `fixed-1x`. Same Key Cavern view, drawable, MetalFX,
  aspect/fullscreen/AA; only internal resolution changes to 1x. Nominal 1920×1080 follows
  the current Apple runtime path. Do not change macOS display mode.
- Legacy A/B/C Instruments scenarios and the plain original command remain available.
  DA/DB/DC are a new namespace; they do not rename or overwrite historical sessions.

## Outputs and privacy

`~/Developer/LASRecomp-Metal-Research/profiling/sessions/<UTC>-DA|DB|DC-baseline-2880x1800-dynamic-log-phased-<id>/`
contains private data and raw local logs (keep local), plus **safe-summary.zip** to share.
The ZIP allowlists only summary/phase metadata, numeric sanitized events, analysis, errors
and a readable REPORT.md. It excludes original settings/saves/assets, binaries, raw logs,
XML, GPU traces and screenshots. Private copies persist even after interruption; do not
remove them while a game process is alive. Ctrl-C never kills the game; quit normally.

The summary separates phases. FPS is ~one-second reported block averages; p95/p99 of the
reciprocal are **not per-frame latency tails**. True frame-time distributions are unavailable
without a full series. Hitches are logged present gaps over 40 ms, not measured CPU stall
duration. G/W are controller estimates from asynchronous completion accounting. Factor
durations use log-read timestamps (0.1 s polling plus buffering); two seconds at each phase
edge are excluded, with edge events retained in the sanitized event stream. Missing values
stay unavailable. Target allocation and content size are distinguished.

For review share this session's **safe-summary.zip** and your visual notes. Do not share raw
captures or logs automatically. Run files are not evidence of success unless their status
and phase quality flags support it; even clean status still requires technical review.

Optional reanalysis (no game launch):

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/dynamic_log.py /absolute/path/to/session
```

Identity/phase mismatches or insufficient data do not replace a good prior ZIP. Separate
`dynamic-analysis-status.json` and, for insufficient metrics, `dynamic-analysis-error.zip`
report the current analysis problem. A corrected retry leaves capture metadata/sidecars
unchanged. Treat that status as the latest analysis outcome.

## Only after an anomaly: focused Instruments investigation

Append `--dynamic-trace metal` for an **8-second** Dynamic Metal System Trace, or
`--dynamic-trace overview` for 25-second Game Performance Overview. This reuses the audited
PID attachment/recording/shutdown code and private launch. It performs warm-up and one
stationary trace, not the normal three-phase observation, and uses a separately labeled
`dynamic-metal`/`dynamic-overview` folder. Stay still until completion after trace saving.
Raw trace/TOC stay local; the safe summary contains no invented per-pass/GPU distributions.
Inspect the timeline/selected interval manually. Capture permissions and populated real-game
tracks remain unverified. Full-frame capture and replay/counters remain a later capability
gap; the previous one-command-buffer workflow is not a complete frame.

## Comparable screenshots, if useful

After measurement ends (not during the steady sample), an ordinary macOS screenshot can
record the same camera view in Dynamic and fixed 1x. Keep images local by default and out
of the safe archive. Screenshot size is display output, not proof of internal resolution;
nearby logged factors provide approximate context, not exact frame alignment. An OS capture
can hitch the game, which is why it is outside measured phases. Do not enable renderer shot,
warp, forced-scale or other test overrides for this baseline.

## Decision rule

First ask whether Dynamic provides sustained ~60 with acceptable sharpness and no observed
artifacts, how much time it spends below fixed 1x quality, and whether the original view
recovers after movement. Then inspect floor/holds, G versus W, spikes and legitimate backoff.
A 30 FPS period alone is not a defect; a reversal count alone is not visible pumping. Repeat
borderline results. If the baseline already meets the goal, recommend no controller change.
