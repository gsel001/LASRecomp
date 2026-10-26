# macOS packaging: verify the shipped symbol providers

`make app` already rebuilds the application with the pinned `build/deps` prefix and
`APP_MIN` deployment target. `make dmg` uses that path. The observed launch failure
came from a separately assembled local installation, not a demonstrated failure of
that standard recipe: an executable linked against Homebrew FFmpeg was combined
with older self-contained FFmpeg libraries. Changing install names did not change
its recorded two-level symbol binding. `_av_frame_clone` was declared as coming from
`libavcodec.63`, while that bundle provided it through `libavutil.61`.

The local installation was repaired by relinking against its exact shipped
libraries; the user confirmed startup. This source change adds a reproducible
packaging safeguard. It does not change rendering, input, pacing or game code.

## Build and validation

Keep the normal dependency/helper/compiler preparation, then run `make app` or
`make dmg`. No new package dependency is introduced: the gate uses Python 3.9+
standard library, Xcode `dyld_info`, `otool`, `lipo`, and `codesign`. When changing
compiler flags, deployment target or dependency prefix, use a fresh build directory;
Make does not generally track command-line changes as file dependencies.

```sh
python3 tools/test_macos_bundle.py
python3 tools/validate_macos_bundle.py 'build/LAS Recomp.app'
```

`bundle_macos.sh` invokes the validator after signing and before reporting success.
Failure stops `make app` and therefore the disk-image/release path. The synthetic
regressions also run in the existing macOS CI and release jobs.

The bundler resolves the input image's rpaths/loader paths, uses original source
images while recursively copying dependencies, and rejects different libraries
that would collide under one bundled filename. It no longer guesses a generic
Homebrew directory when resolving an `@rpath` dependency. This preserves the actual
linked dependency set; it does not silently relink or repair arbitrary inputs.
If a prelinked executable is incompatible with its chosen library set, packaging
must fail. Rebuild/relink against that set instead of pooling symbols across libs.

For a disposable full packaging check, an optional second argument chooses a new
output path; an existing custom output is refused. The default output and existing
architecture, deployment-target and signing rules are unchanged:

```sh
bash tools/bundle_macos.sh build/mac15/lasrecomp '/tmp/LAS-check.app'
```

Do not replace a working installed app just to run this check. The script and
validator never start the packaged executables.

## What the gate proves

For every bundled Mach-O executable, each architecture slice and its linked
non-system dependency closure, the validator resolves dependencies inside the app,
checks architecture availability, and verifies each import against its **declared
provider**. It follows symbol-specific re-exports (including aliases) and whole
library re-exports, bounds cycles, and rejects ambiguous provider names. Required
missing imports or non-system libraries outside the bundle are errors. Unsupported
tool output fails closed. A final strict/deep signature check covers the bundle.

A symbol being present somewhere in Frameworks is insufficient. The regression
creates tiny synthetic C libraries: the original `_av_frame_clone` mismatch fails
even though avutil contains the symbol; relinking against the shipped libraries and
legitimate re-exports pass. No game files or compiled fixtures are committed.

System-cache imports and flat/main-executable/weak-coalescing lookup are reported
separately rather than claimed as verified. Optional missing weak imports are also
counted separately. Non-system symbol re-exports routed through the system cache
are conservatively rejected because this static check cannot verify that route.
Libraries loaded only via `dlopen`/managed-language plugin discovery are outside
the static linked closure. Codesigning, architecture checks and the release's
existing no-game-code/content checks remain necessary.

Dependency-only checks do not establish gameplay, graphics, controller reliability
or game-data validity. A local SDK build is not a substitute for the macOS 15
release build. The installed repaired executable and its user-confirmed launch are
separate evidence from a newly packaged disposable app.
