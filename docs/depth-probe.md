# Metal depth-only draw probe

This is measurement-only instrumentation for issue #67. It does not remove fragment shaders, create pipelines or
textures, change rendering, or change synchronization/pacing. `LARECOMP_DEPTH_PROBE=1` enables it; unset or `0` disables
it. The environment is read once. It is Metal-only; shader metadata and the translator are unchanged.

From the repository root, run the already built executable normally:

```sh
LARECOMP_DEPTH_PROBE=1 LARECOMP_LOG_PACE=1 ./build/lasrecomp
```

Choose the existing installed game and save as usual. Do not change resolution or other graphics settings between
baseline/probe comparisons. For the M1 benchmark, keep Original 16:9, Match display and AA Off, and compare the same
Key Cavern room/camera/actions. The regular `lasrecomp.log` in the configured data folder contains the probe lines;
the runtime handles logging, so no shell redirection is needed. This command does not select a macOS display mode.

## Counts and reporting

Summaries are emitted at the existing renderer-stat reporting points, at least five seconds apart (normally about
six seconds with the default two-second stats interval). Counts cover the interval since initialization or the last
probe report; they reset at reboot. An unfinished final interval is not flushed at quit. For example (illustrative
counts, not an M1 measurement):

```text
[depth-probe] frame 900 interval 6.0s total=60000 depth_only=12000 potential=9000 excluded(overlap): discard=3000 depth_output=0 memory=0 msaa=0 coverage=0 unknown=0 gmem_read=0 (completed NVN draws; potential is not proof of safety)
[depth-probe] depth target 2048x2048 total=12000 depth_only=12000 potential=9000 excluded(overlap): discard=3000 depth_output=0 memory=0 msaa=0 coverage=0 unknown=0 gmem_read=0
```

- `total`: completed NVN draw commands, matching the unit of the existing renderer draw counter. Skipped commands
  (including pending programs/pipelines), clear/copy helper draws, and shader-preparation jobs are excluded. An NVN
  draw may become several Metal draws or instances; it still counts once. These are not fragment or pixel counts.
- `depth_only`: a depth-capable attachment with no actual color attachment. Color attachments with zero write masks
  are deliberately outside this first probe, as are stencil-only passes. Empty color slots do not count as attachments.
- `potential`: depth-only draws with none of the exclusions below. This is a conservative opportunity count, not a
  certificate that fragment removal is safe or that it will save GPU time.
- Each exclusion counts independently, only for depth-only draws. A draw can increment several reasons; their sum
  need not equal `depth_only - potential`.
- Group dimensions are the actual Metal depth attachment's allocated pixel extent, read from the existing pass
  descriptor (including views). They are not the viewport/scissor, Dynamic active area, or shaded pixel count. At most
  eight sizes are retained per interval; additional sizes go into `depth target other`, without losing totals.

The disabled path is a cached branch at pass/draw/stats points. Enabled draws use bounded counters and a metadata
scan only for depth-only commands; there are no per-draw clock reads, allocations, locks, GPU queries or log lines.
Periodic logging still has overhead: compare runs with the probe off/on before treating small timing changes as real.

## Conservative exclusions and uncertainty

- `discard`: `ShaderInfo.uses_discard`.
- `depth_output`: `ShaderInfo.writes_depth`.
- `memory`: known global stores or any image resource. Image metadata does not distinguish reads from writes, so
  image reads are excluded too.
- `msaa`: actual depth attachment sample count greater than one.
- `coverage`: alpha-to-coverage is enabled.
- `unknown`: missing/failed/non-fragment translation metadata, malformed resource counts/types or constant-buffer
  masks, bindless resources, GLSL-only mapped memory, unexpected fragment point-size output, non-2D depth targets,
  invalid color-slot count, or missing depth dimensions/sample count.
- `gmem_read`: global memory is read without a reported store. These draws are conservatively excluded separately
  from known side effects; a future optimization may prove some safe.

`ShaderInfo` has no general sample-mask/coverage-output or complete side-effect certification. The translator itself
notes that sample-mask output is not translated. This probe reads the current flags; it neither parses shader source
nor strengthens that contract. Successful translation does not prove that all future instruction effects are tracked.
Texture allocation size alone does not establish that a shadow pass is expensive. Cold pipeline preparation may
reduce completed counts; measure warmed gameplay and exclude menus/transitions. No shader code or assets are logged.

## Decision and validation

Run `python3 -B tools/test_depth_probe.py` for synthetic classification, overlapping exclusions, bounded grouping,
64-bit counts, formatting and reset tests. It compiles the production header with ASan/UBSan using temporary files.
`make -j6 build/lasrecomp` builds only the host executable, avoiding the generated game-code library target.

If `potential` stays zero or negligible in warmed Key Cavern frames, do not implement this optimization. If it is
substantial and concentrated in recurring depth targets, first inspect GPU pass timing using available profiling
tools. Counts alone cannot estimate saved milliseconds. The low-mode benchmark needs roughly 1.82 ms reduction from
its reported 16.82 ms median to the pacer's 15 ms release threshold, and roughly 2.32 ms to reach a 14.5 ms target;
tail latency also needs improvement. Only a separately approved, guarded fragment-elimination A/B experiment could
establish that gain and validate foliage cutouts, shadows, stencil, depth-output shaders, particles and transitions.
Keep the production pacer, fences, overlap snapshots, write watches and exposure-state preservation enabled.
