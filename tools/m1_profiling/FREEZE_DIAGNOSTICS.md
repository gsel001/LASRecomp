# Beta 6 freeze diagnostics — prepared, not gameplay validated

This extends profile.py, recovery.py and dynamic_observe.py. No game was launched during preparation. The confirmed incident was at **Kanalet Castle, upper part, right-hand entrance**, immediately on entry: Link, menu and flames stopped while FPS/render activity apparently continued. The user used ordinary Quit, not Force Quit. Earlier uncertainty about the location/quit method is superseded; the freeze-onset time and responsible thread remain unknown. Original reports/evidence remain unchanged.

## Commands and procedure

Normal lightweight intensive test (explicit new build; default selection remains the old baseline):

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --build beta6 --intensive --dynamic kanalet
```

Use `--intensive-seconds 600` for ten minutes. Existing Key Cavern, Goponga, fixed controls, repeat crossing, combat and separately selected Overview/Metal modes remain available. `--no-watchdog` disables automatic polling but preserves manual emergency registration. Existing defaults and save-copy isolation remain intact. Use `--build baseline` for a separately labeled old-build comparison. The Beta 6 local catalog pins source HEAD and executable SHA256 and rejects drift. The development executable uses installed local Homebrew libraries; it is not a portable release.

Recommended first targeted test, optional pre-armed Time Profiler:

```sh
python3 ~/Developer/LASRecomp-Metal-Research/profiling/profile.py --build beta6 --prearm
```

Before LAUNCH, listen to the voice check and adjust Mac output/volume. Type VOICE to repeat. After LAUNCH, reach the **outside of Kanalet Castle's upper-right entrance**, before crossing. Keep Dynamic + MetalFX, Original 16:9, fullscreen, AA Off and the existing 2880×1800 drawable. Type READY only there, then refocus. Do not change settings to manufacture load. These are private save/settings copies; originals are not edited.

After READY, stopwatch fallback:

| Time from READY | Normal intensive | Pre-armed entrance test |
|---|---|---|
| 0–10 s | Refocus fullscreen | Refocus fullscreen |
| 10–40 s | Warm up | Warm up outside doorway |
| 40–70 s | Stationary baseline | Stationary baseline; request 120 s Time Profiler |
| 70 s | Intensive play begins | Cross right-hand entrance on cue |
| 80–200 s | Continue intensive play | Stop when safe; stationary recovery |
| 370–490 s | Stop when safe; 120 s recovery | Completed (allow diagnostic finalization) |
| 490 s | Recording complete; quit normally | — |

For 600 s intensive play, recovery begins at 670 s and ends at 790 s. Speech has no effect on these measured boundaries. If an event overruns its cue or an unexpected interruption occurs, annotate affected phases after normal quit. Intended combat, effects, loading, room/camera transitions during the event/intensive phase remain evidence, not automatic contamination. Recovery is required to be stationary/safe. If the game exits, logging finalizes incomplete evidence instead of waiting out the remaining recovery.

The pre-armed trace is requested 30 seconds before the crossing cue. Its 120 seconds nominally cover that baseline, the 10-second crossing and ~80 seconds of recovery, **not the entire recovery or stress test**. Attachment/startup may shorten useful coverage. Check actual trace start/end/duration in diagnostic outcomes; no preparation test proves attachment precedes the doorway. An attachment failure does not pause the stopwatch. For a persistent visible freeze use the emergency launcher before quitting.

## Emergency capture

Double-click `~/Desktop/Capture LASRecomp Hang.command` after swiping away from fullscreen. Leave the game open. The launcher independently discovers exactly one live registered profiling session, verifies kernel process start time, PID, executable path and binary hash, then requests a 10-second all-thread `/usr/bin/sample`. It rejects stale, reused or ambiguous PIDs. It works if the main profiler has crashed, provided its registered game process survives. It cannot discover arbitrary unregistered games.

After sampling, it attempts **Time Profiler for 20 seconds**. It never kills/restarts the game. A successful sample is saved before Instruments starts. A pre-armed recorder is asked to save its partial trace when sampling begins; an existing selected recorder is allowed a bounded wait, rather than attaching a second heavyweight profiler. Sample startup never waits for Instruments. Sampling may briefly overlap recorder shutdown; evidence priority is thread sampling.

Wait for the diagnostic-complete announcement before ordinary Quit. If collection fails or another recorder remains active, speech says so. Nominal sampling is 10 s (25 s process deadline), recorder coordination up to 35 s, recording 20 s plus up to 60 s finalization, export up to 30 s. The normal profiler waits up to 240 s **after measurement** for pending diagnostics, then reports a timeout if still active. No waiting shifts the measurement windows. macOS permission failures remain local; no sudo, security changes or Accessibility access are used.

Each diagnostic attempt gets a new `sessions/<id>/diagnostics/<timestamp>-<trigger>-<id>/` directory. Raw sample, trace, recorder errors, full context and manifest stay there locally. Its allowlisted `safe-summary.zip` contains only typed diagnostic outcomes and a README. Finder is requested to reveal that exact ZIP after manual/automatic collection; pre-armed results are summarized with the main session ZIP to avoid stealing focus mid-test. Do not share raw samples/traces/logs. Existing evidence is never overwritten.

## Detection and uncertainty

The default external Python watchdog checks every 2 seconds. It requires an explicit existing runtime `[hang]` report, at least 30 seconds without fresh render-log frame progress, a confirmed measurement phase and a previously observed non-menu level. It does not treat low FPS, silence, a stationary image, planned room entry, combat or a missing simulation counter alone as a hang. Max two automatic/manual captures per session, minimum 300 s between attempts. Pre-armed capture is separate. Captures are serialized and bounded.

This is conservative **suspected-hang detection**, not universal detection. A long legitimate loading event with an explicit runtime hang report can still be a false positive. Mac application responsiveness, guest input acceptance and simulation/world progression are reported as **unavailable**, never inferred from FPS. Continued rendering may conceal the confirmed incident type. Polling overhead has not been measured in real gameplay; mock performance cannot establish its gameplay cost.

Local context includes exact identity/revisions/hash, latest timestamped FPS, compile count, Dynamic decision/GPU estimates and pacing state when logged, recent scene/slow reports, phase and raw log references. Runtime timestamps and observer UTC are distinct. Disk/load state is not continuously observable. Existing numerical reports retain frame gaps, threshold episodes below 55/45/35 FPS and 30 FPS hold timing. GPU estimates are runtime proxies, not complete-frame measured GPU latency. Time Profiler samples running threads; the all-thread process sample is especially important for blocked waits. Overview remains selectable for GPU/FPS follow-up; Metal System Trace is reserved for justified scheduling questions. No automated GPU resource capture is added.

A future separately approved opt-in heartbeat could log a monotonic counter from a known gameplay simulation update, with pause/loading state and host UTC correlation, perhaps once per second. It must distinguish intentional pauses from stopped simulation and be assessed for overhead. **No simulation heartbeat or simulation-code change is implemented here.**

## Voice and fallback

`/usr/bin/say` runs in background workers. A shared nonblocking audio lock prevents overlapping cues across processes; stale/conflicting phase speech may be skipped rather than shifting a boundary. Diagnostic speech waits only in its own worker, never in measurement code. If speech fails, use the stopwatch table and keep emergency diagnostics open until its result is printed. Volume/audibility requires the user's ears; subprocess success cannot verify the output device.

- READY: “Get ready. Return to the game in fullscreen. Recording begins shortly.”
- Warm-up: “Warm-up starting. Allow 30 seconds for the game to settle. A separate stationary baseline follows.”
- Baseline: “Baseline measurement starting. Stand still for thirty seconds. Intensive gameplay will begin afterward.”
- Intensive: “Intensive gameplay begins now. Fight enemies, move between rooms, and explore demanding areas for 5 minutes.” (actual configured duration substituted)
- Recovery: “Intensive gameplay complete. Find a safe position and stand still. We are measuring performance recovery for two minutes.”
- Completion: “Recording complete. You may quit the game normally.”
- Suspected freeze: “Possible game freeze. Diagnostic collection is starting.”
- Sample success: “Thread sampling complete.”
- Instruments: “Instruments attachment requested. Diagnostics are still running.”
- Successful/partial evidence saved after bounded capture: “Diagnostic capture complete. If the game is still frozen, you may now quit.” Failures/timeouts have distinct messages.

Before gameplay, use the independent volume test:

```sh
/usr/bin/say 'LAS Recomp voice check. Adjust your volume now. No game is starting.'
```

## Source mirror and validation

The fork's `tools/m1_profiling/` is a source/test/documentation mirror. Deploy to the existing research directory to use real local inputs. `BETA6_BUILD_LOCAL.json` is a private machine-specific catalog, excluded from GitHub and sharing ZIPs. No replacement research repository was created. Dependency hashes pin all executable support files, including the Desktop launcher source.

Mock validation covers PID reuse/hash drift, healthy/no-heartbeat behavior, false alarms, sampling denial/timeouts, correct PID attachment, trace export/metadata failure, early exit, pre-arm timing, capture locks/rate limits, privacy, voice timing, old modes and publication safety. Native build and CPU-only tests are separate. Actual gameplay detection, permissions/attachment to this game, overhead, audible cues and complete trace coverage remain unverified until the user runs a session. No freeze cause or upstream fix is established by this preparation.
