# Independent-audit fixes

Read both the independent review and JSON evidence at:
`~/Documents/Codex/2026-10-24/referenced-chatgpt-conversation-this-is-an/outputs/`.

| Finding | Correction | Regression evidence |
|---|---|---|
| Malformed final metadata / unsafe ZIP replacement | Strict TOC root/run/target/data/PID checks with fixed error codes; pending status until validation; original stack/XML retained locally; failure ZIP where writable. All ZIP replacement is temporary-build, CRC/payload verification, atomic replace. Analysis failures keep the existing safe ZIP and create `analysis-error.zip`. | Malformed/missing/empty/incomplete/unexpected/wrong-PID cases, full-session failure ZIP, parser stack preservation, analysis old-ZIP preservation, disk/replace failures. |
| Recorder survives timeouts | Bounded SIGINT→terminate→kill→reap of the owned recorder handle only; signal/exit races and repeated Ctrl-C tolerated; cleanup confirmation saved. Failure/unknown cleanup cannot produce a ready status. | Real synthetic recorder ignores SIGINT/SIGTERM and is killed/reaped; unrelated process remains running. All timeout/race/interrupt paths and error-ZIP finalization covered. |
| Weak sample evidence | Strict finite positive values, increasing runtime timestamps/frame counters, minimum rows, gap/coverage checks, recent warm-up progress, monotonic elapsed clock, settings-file drift and scale-change checks. Invalid evidence withholds distributions. Missing all GPU counters is unavailable, not fabricated; partial proxy intervals are invalid. | Duplicate/backward/short/stale/NaN/zero/missing-period fixtures and full mocked sessions. |
| Wrong comparison constraints | Explicit `repeatability`, `renderer`, `resolution` purposes; required typed build/library/workload/graphics identity. A/Match versus B/1x allowed only in resolution mode. Power/thermal differences reported for review. | Intended A/B resolution acceptance, renderer flag-only acceptance, missing/different library/build/scene/AA/upscaler/drawable/method/motion rejection. |
| External unbundled dependency | Small versioned `isolation.py` is packaged with `DEPENDENCIES.json`; no checkout imports. Every preflight verifies pinned source hashes; isolation drift rechecked before launch. Setup verification and fixture-only dry-run provided. | Clean temporary installation, original 59 tests with nonexistent checkout path, self-check, fixture preflight/isolation tests, helper drift/copy-failure/root-link rejection. |
| Nested metadata privacy | Recursive typed field/enum/number/digest allowlists in `privacy.py`, including analysis and package metadata; unknown values become unverified/absent. No raw log/XML/capture/settings resources enter ZIPs. | Nested path/filename/identifier sentinels, nonfinite/huge numbers, unknown fields/enums, ZIP content checks. |

Additional hardening: runtime `[gamelib]` successful loaded path must match the preflight-
hashed library; fallback-library loading is rejected. Lexical save-root/ancestor links are
checked before resolution (only macOS /var and /tmp platform aliases are normalized).

## Timing policy and remaining limits

Default runtime logs are periodic two-second blocks, not individual frame samples. Runtime
counter IDs must strictly increase but can skip many game frames normally. At least three
rows are required; no time gap above 4.1 seconds; coverage must span at least requested/
measured recorder-lifetime minus four seconds (one period at each boundary), with enough
rows for the two-second cadence. Warm-up uses only newly appended rows over the warm-up
period and checks forward progress against the preceding log. The first measurement block
is excluded from FPS/proxy statistics. A zero/unavailable GPU series is never invented.

Selected CSV v2 includes sample IDs, actual sample timestamps and frame IDs. Per-frame
series require contiguous increasing frame IDs. Command-buffer/pass IDs need not be numeric
or monotonic; multiple buffers/passes may share a frame and timestamp. Selected Overview
intervals need at least 20 seconds, Metal intervals at least five, at least three observations,
coverage to within one second of both edges, no gap above one second, and positive finite
measurements. Missing coverage is invalid, not padded. Partial GPU captures have no claim
of complete timeline coverage.

Runtime proxy windows still bracket recorder startup/stop/save; they are not aligned to
an exact Instruments selected interval. `--notify-tracing-started` was observed in installed
help during review, but a notification listener/start-stop alignment was not implemented or
claimed verified here. Stay focused and still until the completion beep after trace saving.
Runtime settings beyond drawable/scale still require user confirmation and resource review;
a settings-file hash cannot detect a transient change restored before final read. Compilation,
scale transitions, user checks and trace inspection remain necessary. Complete-frame capture,
real-game tracks, replay/counters and actual performance remain unverified.

`capture_created` records an artifact; `capture_validated` becomes true only after all automatic quality/identity and user checks pass. Invalid runtime or metadata evidence leaves it false. This still does not certify an actual GPU performance series.

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
