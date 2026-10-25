# Dynamic resolution: current local implementation review

Reviewed local HEAD `0be6fb2b0e4e2eb34d405ce103261695ddd3b5fd` plus the existing dirty tree.
This is a source review and preparation, not measured M1 Dynamic gameplay. No thresholds,
controller, pacing, MetalFX, allocation behavior or upstream defaults were changed.

## What the implementation does

| Topic | Verified source behavior |
|---|---|
| Geometry | `runtime/nvn/output_scale.c`: Match fits 1920×1080 into the drawable for Original aspect. Dynamic multiplies that scale by `g_dyn`; allocations remain at Match scale (`ax/ay`) while content uses `sx/sy`. A 16384 texture cap remains. |
| Floor | `min(1,max(1/3,540/Match_render_height))`. At a 2880×1800 drawable and Original 16:9, Match's nominal height is 1620; floor factor is 1/3, nominal content about 960×540. This is derived geometry, not texture-readback proof. |
| GPU estimate | `renderer.m:renderer_gpu_busy` consumes completed Metal command-buffer start/end timestamps, subtracting previously counted overlap to form a union on the one queue. Window buffers receive only their share after earlier work. Atomic differences are read asynchronously at presentation; they are not exact per-frame/stage execution timers. |
| G versus W | `metal.m` supplies game union deltas separately from window image/menu/upscale deltas. Window cost is counted by default. Controller averages available G/W over 30 presented frames; ≥15 GPU samples selects the GPU path. Logged `spans summed` is a separate overlapping-span diagnostic, not union/usage/bandwidth. |
| CPU stalls | G/W drives decisions when available. Without sufficient GPU samples, the fallback uses frame durations with samples over 3× median excluded; gaps over 250 ms are skipped. Spikes also prevent counting an increase vote. Slow CPU/loading is not automatically proof that lowering resolution helps. |
| Lower | 14.5 ms normal G+W budget; 3 of last 4 over-budget decisions, 2 consecutive clear misses, or the qualifying near-budget history can trigger reduction. Predicted area scaling of G, measured W, a 0.1 factor grid and maximum 0.3 reduction per step remain. |
| Raise | A next-step prediction `G×(new/old)^2 / 0.8 + W` must fit, with 10 clean consecutive decisions and a raise deadline. Base wait 5 s; undo within 30 s doubles it up to 60 s; a calm minute forgets this backoff. A change applies a 1 s cooldown. |
| Decision rate | `DYN_N=30` counts frames, not fixed half seconds. About 0.5 s at 60 FPS, 1 s at 30, 1.5 s at 20. Vote-based waits consequently last longer at lower frame rates; do not label that alone a defect. |
| Holds/probes | At the floor, measured costs and display waiting can establish 30/20 FPS holds. While held, quality may rise within the slower cadence's 87% budget. Faster-rate headroom and probe timing control release; probe wait starts at 10 s, doubles to 60 s, and a failed probe can inhibit another until improved estimates or 120 s. A short unrecovered observation is censored evidence. |
| Resize / scene | Drawable-height changes preserve approximate content height, reset measurements/votes, and delay a new decision ~1 s; holds adapt their floor/reference. Dynamic does not perform an unconditional per-level reset in this code: it retains scale and adapts through measurements/spike handling. Pacer release votes separately reset on scene/menu/camera changes. |
| Pacer | `pace.c` holds the game's 30 mode for broad sustained overload, with hitch grace and CPU/GPU release tests. GPU headroom thresholds are 15 ms ordinary, 13 ms late-triggered, 10 ms late/backoff. CPU clear/calm criteria and up-to-16× backoff also apply; early return failure doubles the wait. Dynamic steps are not preference changes and do not reset pacing backoff. |
| MetalFX | `metal.m` uses a **spatial** scaler when chosen/supported and content needs enlargement. `renderer_texture_fraction` controls active content; `inputContentWidth/Height` are set separately from input allocations. Scaler resources persist across ordinary Dynamic content changes. The creation log reports allocation sizes, not current active content size. Unsupported/failed creation is detected; no-upscale frames can legitimately use plain sampling. |
| Defaults / 1x | `settings.c` recognizes `resolution=dynamic`, `upscaler=metalfx`, `antialias=off`, `aspect=original`, `fullscreen=1`. Default remains Match. Metal initialization calls `settings_resolve_defaults(false)`: although M1 is physically integrated, this runtime's Apple path does not select the 720-line Intel-style 1x override; fixed 1x nominally means 1920×1080 here. |

Exact sources: `~/Developer/LASRecomp/runtime/nvn/output_scale.c`,
`output_scale.h`, `pace.c`, `metal.m`, plus `runtime/nvn/renderer.m` for GPU union accounting
and `runtime/settings.c`, `settings.h`. Source comments/counters are implementation evidence,
not proof of accurate real-game M1 cost attribution or exhaustive visual correctness.

## Existing coverage and gaps

`tools/test_dynres.c` declares 23 simulated cases: area/fixed costs, FIFO/mailbox, load
changes, near-threshold wandering, clock-drop hold recovery and resize behavior. Its
original runner is unchanged. `tools/test_pace.c`/`.py` cover nine simulated pacing cases,
including overload/release, hitches, backoff and Dynamic-step grace. These unchanged CPU
controller models were inspected rather than rerun; the earlier handoff reports passes.
They do not model all real Metal timing/thermal/visual behavior on this M1.

The existing native `tools/test_settings.py` was reused for the new configuration-format
question: **41 cases passed**, including Dynamic/1x and MetalFX recognition/roundtrip.
No tests were added to the renderer or controller. New tests exercise only preparation,
manual log analysis and wrappers; prior 115 profiling regressions remain in the suite.

The old `tools/dynres_log.py` hard-codes a multi-warp schedule. The new parser does not
import it or assume its START/STEP/warps. It uses explicit manual phase boundaries.

## Questions for actual M1 measurements — not confirmed defects

1. Does unmodified Dynamic settle near sustained 60 in Key Cavern, at what factors and
   visual quality, and does it remain stable for more than a short burst?
2. Does G fall with scale while W stays relatively fixed? The area predictor is a heuristic;
   allocation size alone cannot establish bandwidth or identify a dominant pass.
3. If 30 holds persist, is the floor reached, is G+W still high, or are pacing/headroom,
   CPU stalls, legitimate backoff/probe inhibition or asynchronous timing involved?
4. After the identical camera view returns, does quality recover? Are delay/reversals
   repeatable, or explained by votes, waits, frame rate and different actual workload?
5. Are blur/pumping or visual defects actually observed? Logs cannot establish them.

If the baseline is stable 60 with acceptable sharpness and no defects, leave the controller
unchanged. Otherwise repeat controlled conditions, then use a focused trace for an explicit
question. No new optimization is justified by this preparation or historical no-FS results.

Logged scale is configuration for following rendering and factor text is quantized. Neither a scale-change line nor a descriptor allocation line is an exact present/GPU-frame content-size measurement.
