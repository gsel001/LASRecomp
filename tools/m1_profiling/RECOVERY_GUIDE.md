# Extended intensive gameplay — RI (initial test)

Run the existing launcher in Terminal:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --intensive
```

This uses lightweight logging, **not an Instruments recording**. Keep macOS scaled display at 1440×900, expected drawable 2880×1800. The existing private session settings select Fullscreen / Original 16:9 / Dynamic / MetalFX / AA Off, with the experimental renderer disabled. No original settings/saves or renderer algorithms are changed.

1. Before LAUNCH, hear the automatic voice check. Adjust output/volume if needed; type VOICE to repeat. CANCEL or Control-C ends the check without launching. Type LAUNCH when ready.
2. Manually enter Key Cavern and choose a safe stationary starting position. Confirm settings and type READY. Immediately return to the fullscreen game.
3. Follow spoken cues. During intensive play, fight enemies, trigger normal effects, cross screens repeatedly, enter/exit rooms and play the demanding route that normally causes your drops. These events, including normal transition loads and shader compilation, are intended workload and stay in the data. Do not spend this phase standing still solely to improve the result. There is no forced warp or gameplay automation.
4. At the recovery cue, stop when safe and remain stationary for the full 120 seconds. Choose a safe position without continuing combat or crossing another boundary. If you cannot stop by the cue, finish safely and mark `recovery_1` affected after quitting; the automatic window is not silently shifted.
5. At the completion announcement, quit normally. Mark CLEAN only if you followed timing and had no unexpected pauses, menu/focus/settings changes or other interruptions. Otherwise name affected phases (`baseline`, `intensive`, `recovery_1`), or ALL. Normal combat, screen/room changes and loads during intensive play do not require an interruption flag. Answer the visual-review prompt.

Speech remains asynchronous: no phase waits for audio. It announces return-to-game, warm-up, stationary baseline, "Begin intensive gameplay now", "Stop when safe" for recovery, and completion. No Terminal reading is needed while playing.

**Stopwatch fallback:** start a separate stopwatch when submitting READY. With default 30-second warm-up:

| Elapsed after READY | Default action | With `--intensive-seconds 600` |
|---|---|---|
| 0–10 s | Return to game | Same |
| 10–40 s | Warm up, stationary | Same |
| 40–70 s | Stationary baseline | Same |
| 70–370 s | Intensive gameplay (300 s) | Intensive gameplay 70–670 s (600 s) |
| 370–490 s | Stationary recovery (120 s) | Stationary recovery 670–790 s |
| 490 s (8m10s) | Complete; quit normally | Complete at 790 s (13m10s) |

To extend the first command, add `--intensive-seconds 600` (accepted range 300–600 seconds). If you override warm-up, add its extra seconds to all later cues. If speech fails or a cue is missed, use the stopwatch and flag uncertain timing afterward. There is no need to switch away from fullscreen to mark events; brief route/slowdown notes afterward are useful.

## Results and slowdown interpretation

A new RI timestamped session is created under `~/Developer/LASRecomp-Metal-Research/profiling/sessions/`. After normal completion, its exact **safe-summary.zip** is printed and revealed in Finder. Share that ZIP plus a short account of the route, visible issues and whether the usual slowdown occurred. Raw logs, trace/XML, private copies and proprietary game data remain local. Earlier sessions are never overwritten.

`REPORT.md` shows FPS, gaps, compilation, pacing hold time and recovery, plus durations/counts below **55, 45 and 35 FPS**, and up to five longest below-55 episodes per phase. `recovery-report.json` retains all classified episodes up to the explicit 1000-per-threshold cap (count/truncation reported), including:

- Start/end relative to phase, observer timestamps and runtime timestamps; the clock domains are distinct.
- Observed duration, lowest periodic FPS block and whether the pacer's 30 mode was observed.
- Left/right censoring at phase edges or missing/reset periods. Missing intervals are unknown and never bridge a slowdown or count as recovery.

Thresholds are strict and nested: time below 35 is also below 45 and 55; **do not add totals**. Durations classify complete periodic FPS blocks, not exact individual-frame durations. The first block and unlogged edges are unclassified. Large present gaps and compilation stay as separate timestamped events even if FPS coverage is missing. All partial observations remain available with their quality flags.

`recovery-events.jsonl` preserves FPS, hitch gaps, scale/decisions, controller GPU game/window estimates, compile counts/work, level identity hashes, supported indoor-zone events and pacer hold/release/backoff/grace messages. The report separately counts hold-entry/release events and observed hold state: 30 FPS by itself does not prove the pacer forced it.

Compare high GPU estimates (>16.67 ms nominal 60 Hz budget, and the separate 14.5 ms Dynamic budget), scale/floor decisions and compilation with the slowdown timeline. Estimates below Dynamic's budget while the pacer holds are candidates for review, not proof that the pacer's CPU history and 15/13/10 ms GPU release gates were satisfied. CPU/resource preparation/scheduling may still be unknown; compiled shader counts alone do not prove a stall. Recovery is the existing first >=5-second near-60 sequence with pacer released; a 120-second window can be censored. No reproduced drop means no cause has yet been established.

## Optional follow-up: Game Performance Overview

Only after the lightweight test identifies a repeatable slowdown, add:

`--dynamic-trace overview --intensive-trace-at 240 --recovery-trace-seconds 90`

This requests a separate **Game Performance Overview** capture 240 seconds into intensive gameplay, for 90 seconds. Adjust the offset to the previously observed slowdown. Offset must fall within the selected intensive duration. Logging and all phase windows still continue for the entire stress/recovery test; recording/attachment can perturb performance. A short trace does **not** cover all 300/600 seconds or necessarily all recovery. Verify actual attachment, PID, tracks, timestamps and complete-frame coverage locally in Instruments. The recorded request-to-validation span is not the trace duration; actual bounds must be read from Instruments. Raw captures remain excluded from the safe ZIP.

Existing `--dynamic-trace metal` remains a diagnostic option only when GPU scheduling information is needed. Existing non-intensive recovery, Dynamic and legacy profiling commands remain available below. No automatic recording, optimization or threshold change is performed.

---

# Targeted FPS drops and recovery — preparation only

No game was launched during preparation. No renderer, Dynamic/pacer algorithm, threshold or original save/settings was changed. The existing launcher, private-copy isolation, PID/library verification, runtime parser, recorder cleanup and atomic safe ZIP writer are reused.

## First test: screen transition (RT)

Use the same 1440×900 scaled macOS display, expected 2880×1800 drawable, Fullscreen / Original 16:9 / Dynamic / MetalFX / AA Off. Close other game copies. In macOS Terminal:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --recovery screen-transition
```

Before any game launch, the command automatically speaks a volume-check sentence. Wait until you hear it clearly, using the speakers or headphones you will use for gameplay. Adjust your Mac output volume or audio output if necessary, then type `VOICE` to replay it; wait for each sentence to finish. Type `LAUNCH` only when ready. To test without ever launching, replay with VOICE and then type CANCEL (or press Control-C). No game starts until LAUNCH.

Manually enter Key Cavern and choose a safe, reproducible screen boundary: A is immediately before it, B a specific stationary spot immediately beyond it. Avoid enemies for this test. Remember the direction and camera view. Confirm settings and type READY. Scene selection is manual.

After READY the automatic schedule is:

| Seconds after READY | Action |
|---|---|
| 0–10 | Refocus the game. |
| 10–40 | Warm up, stationary at A. |
| 40–70 | Baseline: remain stationary at A. |
| 70–80 | Cross A→B once, then stop at the chosen B position. |
| 80–200 | Recovery: remain stationary for the full 120 seconds. |
| 200 | Completion cue; quit normally. |

Spoken cues tell you to return to the game immediately after READY, begin the stationary baseline, cross the boundary or begin combat, stop for two minutes of recovery, and close the game normally when recording is complete. Repeat runs also announce the return, settling period and second forward crossing. No Terminal input or reading is needed while playing.

Speech uses the built-in `/usr/bin/say` at 190 words/minute in background workers. Timing never waits for audio playback; all existing phase durations remain unchanged. A failed speech process is nonfatal; a hung process is bounded and only that speech child is cleaned up. A worker delayed more than one second skips its stale cue. Spoken sound can begin slightly after a phase boundary; the logs retain the measured phase bounds, not the spoken word timing. Voice overhead is unmeasured. Existing Terminal text/bells remain secondary.

**Stopwatch fallback:** if speech is unavailable or inaudible, start a separate stopwatch at the moment you submit READY. Use the exact elapsed-time table above (cross at 70 seconds, stop by 80, close after 200). Keep it visible outside the computer, for example on a phone, without switching out of fullscreen. If a cue is missed and timing is uncertain, finish safely and mark the affected phase after quitting. Do not open menus or switch focus during measurement.

After quitting, type CLEAN only if the route/timing matched and recovery began stationary. Planned transition/loading is intended evidence, not contamination. If crossing finished late, there were unplanned events, or combat continued into recovery, enter affected phase names (e.g. `recovery_1`), or ALL if uncertain. Report observed visual issues using the final prompt. Runtime scene/zone logs are partial; user confirmation is essential. Notes about the route, exact observed drop and visible recovery are useful; do not include personal save information.

The launcher prints and reveals this run's `safe-summary.zip` in Finder. Runs use new timestamped directories under:

`~/Developer/LASRecomp-Metal-Research/profiling/sessions/`

Share only that ZIP plus concise route/visual notes. Do not upload `runtime-local.log`, private saves/settings, raw `.trace`, XML, binaries or extracted resources. A failed or interrupted run also produces a clearly marked error summary when possible; it is not a successful measurement.

## Optional: same-direction first/second crossing

Add `--repeat-crossing` to the first command. After the first recovery ends at 200 s, return B→A within 10 s, settle for 30 s, cross the SAME A→B boundary again at 240–250 s, then remain still at B until 370 s. The return is labeled separately and is not the second comparison crossing. This compares first and second use within this session, not a guaranteed cold cache: reaching A may already have prepared resources. Confirm the same route, direction, destination, enemies and conditions after quitting. Persistent differences suggest a hypothesis; they do not prove compilation caused the drop.

## Combat (RC), separate run

Use `--recovery combat` instead. Select a safe reproducible small enemy group in Key Cavern and a safe observation spot nearby. After READY: refocus 10 s, warm up 30 s, baseline stationary 30 s, fight for up to 30 s (70–100 s), stop when safe, then stationary recovery 100–220 s. If enemies remain active, prioritize safety and mark recovery affected. For the stopwatch fallback, start at READY: begin combat at 70 s, stop when safe by 100 s, remain still until the 220 s completion. For the optional repeat-crossing fallback use the timings above: return 200–210 s, settle 210–240 s, second forward crossing 240–250 s, recovery 250–370 s. These tables assume the default 30-second warm-up; add any extra `--warmup` seconds to all later cues.

No forced warps, invulnerability, gameplay automation or original save edits are used. To use a manually selected Goponga location, add `--dynamic goponga`; the runtime cannot verify its human map name.

## What the summary can distinguish

`recovery-report.json` has each phase's FPS sample count/median, reciprocal-block median/p95/p99, present gaps >40 ms, interval compile count/work duration, scale/factor dwell and adjustments, Dynamic holds, observed pacer hold time, game/window/total GPU estimates, and recovery time or censoring. Intentional hitches/compilation are retained in the event and recovery metrics; they are not trimmed into an apparently smooth run. Missing/invalid periods and unexpected interruptions remain quality flags.

`recovery-events.jsonl` keeps numeric, timestamped FPS/compile/gap/scale/decision/hold/zone events, with hashed runtime level identity. Non-timestamped logs use observer monotonic read times (0.1 s polling plus buffering); FPS/hitch lines additionally retain the runtime clock and frame. No raw shader/resource text or file paths pass the allowlist.

Recovery means the first observed >=5-second sequence of 58–62 FPS blocks with pacer released, no compilation or >=100 ms maximum gap, and continuous counters. It is relative to the STOP/recovery cue, not an exact action-end measurement. It does not certify the rest of the window stayed at 60. If no drop occurred, treat this as a non-reproduction. If recovery was not seen within 120 s, report censored, not permanent failure. Late events/interruptions or missing coverage prevent a validated recovery duration.

Interpret evidence in this order:

1. Did FPS actually fall, and was `pace` 30? Runtime `pace 30` reflects the LASRecomp pacer hold, not every possible game-chosen 30 FPS frame. Compare explicit hold entry/release messages.
2. Do compilation intervals, present gaps, or scene/zone events coincide? Summed compile work is not wall stall. Resource preparation can occur without compilation.
3. Does Dynamic hit its floor, keep reducing scale, or remain above its 14.5 ms budget / the nominal 16.67 ms 60 Hz budget? Separate game G from output W.
4. Does estimated GPU headroom return while pacer hold remains? `below_dynamic_budget_while_pacer_held_*` is a candidate interval, not the pacer's exact headroom test. The pacer uses CPU history and GPU thresholds 15/13/10 ms depending on hold cause/backoff; a sub-16.67 ms GPU estimate alone cannot establish releasability.
5. Do explicit CPU-headroom/GPU-rejection or release messages explain it? Otherwise CPU, scheduling, preparation and backoff remain hypotheses. Do not disable holds or alter thresholds to inflate FPS.

Verified source behavior: scene/camera-zone changes restart pacer release counters; grace excludes frames after signaled hitches; rapid failed releases double backoff up to 16×, giving up to about 80 s on the enough-headroom path. Dynamic separately has conservative raises/probes/backoff. These are possible explanations, not a diagnosis of this M1 run.

Limitations: periodic FPS/reciprocals are not per-frame latency tails. G/W are asynchronous controller estimates, not synchronized full-frame execution or utilization. Log formats quantize scale/timing. Factor dwell forward-holds the logged state; missing decision coverage is flagged. Indoor zone logging only covers supported camera paths, not all outdoor screens or every internal pacer scene reset. No exact resource-preparation timeline or default continuous CPU-cost series is available. Nominal thermal state does not prove or exclude throttling.

## Optional focused diagnostics — only after a reproducible issue

Add `--dynamic-trace overview` to the relevant recovery command. This is a separately labeled, instrumented run using **Game Performance Overview**, not the default passive run. The recorder is requested ten seconds before the first event cue, during the final baseline portion; attachment may still lag, so verify actual coverage in Instruments. Passive logs continue through the entire 120-second recovery. The default 25-second trace will not capture the whole recovery; add `--recovery-trace-seconds 150` for a longer attempt when justified (allowed 5–180 s). Overhead may alter behavior. Compare with an untraced reproduction.

Use `--dynamic-trace metal` only when additional GPU scheduling information is needed; duration is independently configurable. Neither trace automatically provides valid full-frame GPU samples: PID metadata is checked, but actual tracks, event alignment and frame coverage need manual inspection. Raw captures stay local and out of all shared ZIPs.

If CPU versus GPU gating remains unresolved, `--recovery-pace-details` opts into existing per-frame `LARECOMP_LOG_PACE=1` diagnostics. It records CPU busy/cost, render-thread CPU, waits and delayed GPU deltas. This adds log overhead, so keep it separate from the first passive run. Unconditional hold/release messages already work without it. No internal pacer moving averages/counter history are reconstructed as exact truth.

Default recovery logging adds only `LARECOMP_LOG_INDOOR=1` to the existing Dynamic/FPS/hitch logging, with `LARECOMP_DEPTH_NO_FS=0`; inherited experimental flags are stripped. Original Dynamic DA/DB/DC and legacy Instruments A/B/C modes remain available.
