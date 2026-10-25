Targeted transition/combat recovery preparation is available via `--recovery screen-transition` / `--recovery combat`; see [RECOVERY_GUIDE.md](RECOVERY_GUIDE.md). Planned events are retained and each recovery lasts 120 seconds. Existing modes below remain available.

The primary next session is now **Dynamic DA**; use DYNAMIC_GUIDE.md. The following
fixed-resolution procedure is retained for optional detailed investigation/historical continuity.

# First session: Key Cavern, Retina baseline (A)

1. Quit all other LAS Recomp copies normally. Connect to your usual power source and
   record whether it is AC or battery; do not change performance controls mid-session.
2. Manually set macOS display to **1440×900 scaled**. Expected Metal drawable is
   **2880×1800**. The launcher does not change display settings.
3. In Terminal run:

   ```sh
   python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py
   ```

4. Read preflight output and type **LAUNCH**. This launches the development build with a
   private save/settings copy. No game setup/import/build should appear. If it does, quit
   normally and retain the local error; do not import/extract anything.
5. In the game confirm **Fullscreen**, **Original 16:9**, **Match display**, **AA Off**.
   Dynamic resolution must not be selected. The upscaler is copied unchanged from your source
   settings. The original renderer is forced with `LARECOMP_DEPTH_NO_FS=0`.
6. Enter the **same Key Cavern room and position previously benchmarked**. Load and shader
   activity must settle. This exact position is confirmed by you; a level token alone
   cannot prove the exact room/camera/route.
7. Return to Terminal and type **READY**. Within **10 seconds**, refocus the game. Stay
   still for the following **30-second warm-up**, then for the **25-second capture and trace saving** (remain still until the beep).
   The launcher attaches by verified PID through Instruments' command-line interface;
   you do not need to bring Instruments forward. Leave the game focused throughout.
8. A beep indicates completion or the console reports a failure. Quit LAS Recomp normally.
   Return to Terminal. Type **CLEAN** only if the recording contained no loads, menus,
   focus/fullscreen transitions, settings changes or unexpected movement.
9. Read the final status. Share only the printed **safe-summary.zip**. Keep raw traces local.
   A created trace still requires inspection of its stable selected interval in Instruments.

Private empty caches may cause more compilation than earlier runs. If recent stats still
show compilation after warming, the launcher rejects that attempt. Quit normally, then
retry with `--warmup 120` (up to 300 supported), allowing enough room time for the last
three periodic compile counters to reach zero. Some loading/compilation can escape these
coarse counters: inspect the timeline before treating any interval as steady gameplay.

If actual drawable or render scale fails validation, quit normally and start a new session
with corrected display/in-game settings. Do not mix an in-session correction into the old
sample. Any invalid capture is preserved and labeled; it is not evidence of game performance.

## Expected and observable state

| State | A / C | B | Verification |
|---|---|---|---|
| macOS logical display | 1440×900 | same | Metadata helper where available; manual selection |
| Drawable | 2880×1800 | same | Actual `[scale]` log required |
| Render scale | 1.5×1.5 | 1.0×1.0 | Actual `[scale]` log required |
| Internal 16:9 area | about 2880×1620 | about 1920×1080 | **Derived estimate**, not observed texture dimensions |
| Resolution | Match | 1x | Private setting + user confirmation; runtime enum unverified |
| Fullscreen / aspect / AA | fullscreen / Original / Off | same | Private settings + user confirmation; runtime flags unverified |
| Dynamic resolution | not selected | not selected | Private setting; runtime enum unverified |
| No-FS experiment | off | off | Runtime `experimental=0` banner required |

Eligibility diagnostics are deliberately disabled, so their detailed periodic settings/source-
texture snapshot is unavailable. Verify actual source/attachment dimensions later in a GPU
capture. A drawable of 2880×1800 does not mean a 2880×1800 16:9 source image.

## Follow-up sessions (optional, not required first)

- **A, Metal System Trace**: same command plus `--method metal`; same readiness procedure;
  default 8 seconds after the warm-up. Use scheduling/overlap evidence, not CPU waits alone.
- **B**: same display/fullscreen/aspect/AA/upscaler/room; append `--scenario B` and confirm
  **1x**. This changes only requested internal resolution. Do not change macOS display.
- **C**: append `--scenario C`; find a reproducible Goponga position with water and vegetation.
  It has no verified Goponga-to-runtime-map-name mapping. You confirm location; the script
  checks a stable non-menu runtime level. An outdoor scene is not assumed more expensive.
- **Movement**: a fresh session with `--motion movement`; follow a short reproducible route
  after warm-up. Intentional route movement is allowed; loads/unplanned movement invalidate
  stationary comparisons. Keep movement statistics separate from stationary sessions.

## GPU capture: separate, intrusive investigation

`--method frame` starts a distinct capture-enabled baseline session and uses the locally
verified `gpucapture boundaries --pid PID` and `gpucapture start --pid PID --count 1 --output PATH`.
It writes `partial-command-buffer.gputrace`. The default boundary captured one command buffer
in synthetic validation. LAS Recomp uses several buffers per frame, so this may miss most
passes. **It is not a verified complete representative frame capture.**

To inspect, open the local `.gputrace` in Xcode, identify the captured encoders and dependencies,
and verify which frame/queues it covers. Replay and GPU counters have not been tested here.
If installed tools expose an appropriate frame/scope boundary during gameplay, inspect it
before using a verified `--boundary ID` command manually. Do not guess an ID, assume `--count 1`
is a frame, or combine unrelated buffers as per-frame statistics.

No explicit MTLCaptureScope was found in the inspected game Metal backend. If existing
capture boundaries/Xcode UI cannot cover a complete frame, the smallest safe follow-up is
a separately authorized capture-scope hook around all game-frame queues, with capture code
only enabled for profiling. That would modify the renderer and is **not authorized or done**
in this task. A timeline can still identify scheduling and expensive intervals before that.

Raw `.trace`, exported XML and `.gputrace` stay local: they can include textures, shaders,
process environments and personal paths. Never upload them with the safe summary.

## Audit-fix acceptance checks

Warm-up must contain newly appended, forward-moving runtime samples; a stale log cannot
arm capture. The successful loaded-library path must match the hashed library, in addition
to the baseline banner and drawable/scale checks. Duplicated/backward frame counters or
runtime clocks, missing periods, short coverage, settings-file/scale changes and failed
trace identity produce failed/inadequate evidence. No exact GPU metrics are manufactured.
A ready status means automated workflow checks passed and still requires selected-interval
trace inspection. It does not prove GPU saturation or a renderer benefit.
