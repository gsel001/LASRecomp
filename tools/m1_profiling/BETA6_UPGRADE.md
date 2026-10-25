# Beta 6 follow-up integration — selected revision 5443be2

Branch `codex/m1-beta6-update-5443be2` integrates upstream `5443be29ff788063fa23eba8080925390a71af0c` with the preserved M1 experiments. Upstream adds RomFS path/size validation, extra-file diagnostics and save-test stubs. Controller/pacer/settings/kernel remain unchanged relative to this selected upstream. Original development source modifications remain preserved.

The local installation had six redundant RomFS root files: `main`, `main.npdm`, `rtld`, `sdk`, `subsdk0`, `subsdk1`. Each was SHA256-identical to its ExeFS original. At user request only those RomFS duplicates were removed. ExeFS originals, eight save files and settings retained their hashes. The remaining inventory matches all 3,836 expected RomFS path/size entries. No game resources, saves, binaries, local catalogs or raw evidence are published. Removing duplicates establishes neither a freeze cause nor a performance improvement.

The arm64 app build, signature, upstream game-address/save tests and both profiling dry-runs passed. The internal upstream label remains `beta_5.2`; branch/revision identify the development build. An upstream reference check during publication found newer commit `77cfeb893f0faa7412d7aecee530d8ac2616f49f`; this publication matches the installed 5443be2 integration and does not claim newer code was validated. No game was launched.

The initial preparation record follows as a historical milestone.

---

# Beta 6 integration record

Verified live upstream `peiikai/LASRecomp:beta_6` at `4e9979c714095aaa0d6d2128a65601503eddd3ee`. Previous local development HEAD was `0be6fb2b0e4e2eb34d405ce103261695ddd3b5fd`, based on an earlier Beta 6 (`7952364`), not Beta 5.2. Between that base and selected upstream: 74 commits including merges, 47 changed files (+2445/-624). The requested Beta 6 line is retained.

Upstream review included the door/pit landing fix (`16d902e`, #383), Metal storage snapshot reset on reboot (`9906346`), Vulkan overlap/Mali fixes, save editor/UI and platform changes. The reboot reset is not an established fix for the reported Kanalet doorway freeze. No reviewed upstream change can be claimed to solve the incident without reproduction/thread evidence.

Isolated branch `codex/m1-beta6-freeze-diagnostics-v1` starts at selected upstream, then cleanly ports the existing two opt-in M1 commits (`32c7f9f`, `0be6fb2b`) and all six modified/six untracked original experiment files. The original working branch and files are preserved. Changes include diagnostic depth probes, conservative no-fragment eligibility/attachment checks, translation test controls, and diagnostic/A-B collectors. Existing experimental paths remain opt-in; profiler forces no-FS optimization off. Upstream Dynamic controller, pacing, settings and kernel code are unchanged. Failed/inconclusive experiments are preserved, not removed or enabled.

New profiling support extends the existing launcher; see FREEZE_DIAGNOSTICS.md. Public source excludes binary/app, local build catalog, game library/assets/saves, raw traces/samples/logs, private paths and session outputs. The separate research directory has no Git repository/verified private remote; only this source mirror is versioned in the authorized fork. No public research repository/PR/comment was created.

Build: `make -j4 build/lasrecomp`, Apple Silicon arm64, existing project development settings and installed SDL3/FFmpeg/Homebrew libraries; Metal/MetalFX linked. No dependencies installed. Separate development app is a local wrapper around the validated executable, not a signed portable distribution and not a replacement for the installed app. The executable and local catalog are hash-pinned; actual commit/build hash are in preparation metadata. No executable was launched.

Validation: 285 profiling mock tests, nine native/CPU-only test scripts, existing settings/Dynamic/pacer checks, arm64/linkage/plist checks and launcher dry-runs. Default translation comparison could not use missing shallow-history REF `652e234`; the explicit `GLSL=0 REF=origin/beta_6 bash tools/test_translate.sh 1000 2 msl` comparison completed with zero MSL differences for 1000 attempted programs (721 translated; 279 translator-rejected programs, not mismatches). GLSL path, Metal GPU execution tests, synthetic GPU benchmarks and gameplay were intentionally not run. No preparation test proves visual correctness, speed improvement or freeze resolution.
