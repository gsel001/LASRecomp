# Beta 6 freeze preparation — current milestone

285 Python tests pass, zero final failures. Nine CPU/native test scripts pass, including 352 depth-attachment checks. The arm64 build and zero-difference MSL upstream comparison pass. Three original regression suites plus all existing modes remain covered. No game, real hang sample, GPU execution benchmark or new Instruments recording was run. See BETA6_UPGRADE.md and FREEZE_DIAGNOSTICS.md for limitations and the initial shallow-reference translation failure. Four pre-existing session document/Finder metadata files changed during preparation; original source/Git/build hashes and the other 488 session files match entry. Full preservation details are retained locally.

Historical milestones follow.

# Intensive RI validation — current milestone

239 Python tests passed (211 previous + 28 intensive-related), zero final failures/skips. Mocks cover 300/600-second plans, CLI validation, speech, event inclusion, nested slowdown episodes/timestamps/censoring, missing/nonmonotonic periods, >256 sanitized episodes, RI metadata/settings, delayed Overview request without shorter phases, no default recording, interruptions, trace failure, save isolation and Finder reveal. No game, actual speech, GPU benchmark or Instruments recording was run. Historical validation follows.

# Spoken recovery cues — current validation

211 Python tests passed (199 existing + 12 speech-related), zero failures/skips. Voice playback is mocked: dispatch is asynchronous; missing/failed/hung speech and stale cues are nonfatal; cue content, repeat/combat routing, prelaunch replay/cancel and full mock session cue coverage pass. No game or actual speech played during validation. `/usr/bin/say` is executable on this Mac; audibility requires the user prelaunch voice check. Existing phase durations, game isolation, privacy and analysis regressions pass. Historical validation follows.

# Targeted recovery validation — October 25, 2026

199 Python tests passed (155 existing + 44 recovery); zero final failures/skips. Fixtures only, no gameplay/GPU benchmarks. Both recovery protocols, repeated route, safe saves/settings, interruptions, optional trace failure and ZIP/reveal tested. See RECOVERY_GUIDE.md and validation/tests-safe.json. Real gameplay/trace coverage remains pending. Prior validation below remains historical.

# Dynamic preparation validation — October 25, 2026

**155 Python tests passed: 115 prior profiling/audit/recovery tests plus 40 Dynamic tests.**
**41 native settings parser/default/roundtrip cases passed** using the existing source test
runner and temporary INIs only. No game, original saves, GPU workload or old 3,200-measurement
benchmark was launched. The controller/pacer source is unchanged; its existing model tests
were inspected, not redundantly rerun. The previous validation history follows below.

New coverage: exact private Dynamic/MetalFX/AA/Original/fullscreen settings, controlled
flags, all three scenario IDs, CLI routing, missing log support/dependency propagation,
explicit phase boundaries and monotonic scheduling, FPS/scale/GPU missing-data handling,
weighted factor dwell/recovery/censoring, holds and present-gap events, compilation/scene/
drawable contamination, startup transitions excluded from steady phases, return-room
identity, sanitized archive members, wrong-session/failed-analysis retry preservation,
mock full observation with no Instruments, optional focused PID trace, failed launch,
Ctrl-C/save lifetime, visual issue versus unchecked state, and safe finalization failure.

Actual game/scene navigation, exact active content dimensions, real MetalFX operation,
first gameplay logs, real trace permissions/populated timing tracks and complete-frame
coverage remain unverified. No optimization or controller defect is asserted.

# Audit-fix non-gameplay validation

**115 tests passed: the independently verified 111 plus four analysis-retry regressions, zero failures/skips.**
The retained suite's fixture streams now cover genuine warm-up/capture durations, use the
bundled dependency, and supply the stricter selected-samples contract; its checks were not
weakened to accept the audited invalid cases. See AUDIT_FIXES.md for finding→fix→test mapping.

Validated: Python compile/import/help; packaged dependency hashes; mocked launch/attachment;
malformed/missing/incomplete/unexpected trace metadata; atomic ZIP failures; bounded shutdown
with real synthetic recorder processes; signal races/Ctrl-C/timeouts; timing coverage and
identity; renderer/resolution/repeatability comparisons; synthetic save isolation/copy
failures; dependency drift; root-link rejection; recursive privacy and allowlisting.

The clean-install regression copies only manifest-listed package files into an empty
folder. It runs `profile.py --self-check`, `setup_check.py --fixture-dry-run`, then the
original 59-test suite with REPO pointing to a nonexistent checkout. No actual game save,
game code/library, system tool installation or extraction is required for these tests.

The real-Mac `profile.py --dry-run` separately checks the existing development executable,
compiled library/IDs, data/settings/save paths, tools, Git state and storage without launching
the game or copying saves. Its current result is saved in `preflight/latest-safe.json`.
Fixture checks are never represented as a real-machine capture or real-machine dry-run.

Earlier synthetic capability traces were read, not repeated: Overview, Game Performance
and Metal System Trace attached/exported successfully; gpucapture saved one command buffer.
That proves neither real-game tracks nor full-frame capture. Earlier restricted Instruments
cache access was resolved through approved host execution without system/security changes.
No synthetic GPU benchmark, GPU capture workload, gameplay, renderer modification,
installation, display setting change, Git mutation, push or PR was performed in this fix task.

Original preservation is checked against a new read-only entry snapshot: 699 tracked and
non-ignored source/worktree files plus exact HEAD/status. Before/after inventory digests
and match count are in the sanitized validation record. Original saves/assets and ignored
generated content are not content-hash inventoried; no writes are directed to them.

Local error details/tracebacks/partial traces/private copies remain available. Failure ZIP
creation is best effort when disk/permissions permit it. Cleanup-unconfirmed explicitly
means the owned recorder may still exist; the game is never killed to compensate.

Recovery regressions exercise valid capture → missing CSV, invalid CSV, mismatched
comparison, or malformed current TOC → corrected retry. They assert unchanged capture
manifest, measurements and every safe sidecar, byte-for-byte ZIP preservation on failure,
separate analysis status/error artifacts, restored successful analysis, original capture
validity/numeric measurements in the replacement ZIP, and compatible comparisons afterward.
Existing malformed capture-finalization and malformed analysis tests remain in the suite.
