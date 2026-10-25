#!/usr/bin/env python3
"""Two manually played, fixed-Match Metal runs. No build, scripted input, or display-setting changes."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

import depth_no_fs_diagnostic as diag

RUNS = (("A-default", 0), ("B-experimental", 1))
GRAPHICS = {"fullscreen": "1", "aspect": "original", "resolution": "match", "antialias": "off"}
BEGIN, END = "[depth-ab] MEASURE_BEGIN", "[depth-ab] MEASURE_END"


def private_run(folder, settings, save, root, mode, parent_env):
    env, private = diag.prepare_private_run(folder, settings, save, root, parent_env)
    # Change only this run's disposable preferences; freeze the same upscaler from the source file in both runs.
    lines = [line for line in private.read_text().splitlines()
             if line.split("=", 1)[0].strip() not in GRAPHICS]
    private.write_text("\n".join(lines) + "\n" + "".join(f"{k} = {v}\n" for k, v in GRAPHICS.items()))
    env["LARECOMP_DEPTH_NO_FS"] = str(mode)
    return env


def measurement_log(source, target):
    """Keep the bounded window plus startup banners/settings anchors. Drop the first straddling draw block."""
    lines = source.read_text(errors="replace").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith(BEGIN)]
    ends = [i for i, line in enumerate(lines) if line.startswith(END)]
    warnings = []
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        target.write_text("")
        return ["Missing or invalid measurement boundaries; no controlled window available."]
    start, end = starts[0], ends[0]
    prefix = lines[:start]
    banners = [line for line in prefix if line.startswith(("[depth-no-fs] experimental=", "[depth-no-fs-diag] enabled="))]
    for kind in ("[depth-no-fs-diag] output ", "[scale]"):
        anchor = [line for line in prefix if line.startswith(kind)]
        if anchor:
            banners.append(anchor[-1])
        else:
            warnings.append(f"No pre-window {kind.strip()} anchor.")
    window = lines[start + 1:end]
    # First interval can include pre-window draws; a block can also be cut in half at either boundary.
    blocks = [i for i, line in enumerate(window) if line.startswith("[depth-no-fs-diag] frame ")]
    complete = []
    for index in blocks[1:]:
        stop = next((j for j in range(index + 1, len(window))
                     if window[j].startswith("[depth-no-fs-diag] shader_cert_reasons(")), None)
        following = next((j for j in blocks if j > index), len(window))
        if stop is None or stop >= following:
            warnings.append("Incomplete diagnostic block at measurement end; excluded from counts.")
        else:
            complete.extend(line for line in window[index:stop + 1]
                            if line.startswith("[depth-no-fs-diag]") and not line.startswith("[depth-no-fs-diag] output "))
    # Timing/output lines keep their original order. Diagnostic blocks are summarized separately; frame numbers remain.
    timing = [line for line in window if not line.startswith(("[depth-no-fs-diag]", "[depth-no-fs]", "[depth-probe]"))
              or line.startswith("[depth-no-fs-diag] output ")]
    target.write_text("".join(banners + timing + complete))
    return warnings


def output_identity(text):
    match = re.search(r"drawable (\d+x\d+) scale ([\d.]+x[\d.]+) allocation ([\d.]+x[\d.]+)", text)
    return match.groups() if match else None


def validate(summary, log, expected_drawable, mode):
    errors = [w for w in summary["warnings"] if not w.startswith("Final partial diagnostic interval")]
    outputs = summary["output_snapshots"]
    identities = {output_identity(item["text"]) for item in outputs}
    if not outputs or None in identities or len(identities) != 1:
        errors.append("Output dimensions/scale/allocation were missing or changed during the window.")
    expected = {"fullscreen": 1, "aspect": 1, "resolution": 0, "aa": 0}
    for item in outputs:
        if any(item["settings"].get(k) != v for k, v in expected.items()):
            errors.append("A measured output snapshot was not fullscreen/Original/Match/AA Off.")
        if not output_identity(item["text"]) or output_identity(item["text"])[0] != expected_drawable:
            errors.append("A measured drawable did not match the requested dimensions.")
    if len({item["settings"].get("upscaler") for item in outputs}) != 1:
        errors.append("Upscaler changed or was unavailable.")
    # [scale] is emitted on changes, so also catch a resolution switch that returned before a periodic output snapshot.
    if len(set(summary["scale_changes"])) > 1:
        errors.append("A scale change occurred inside the measurement window.")
    if not summary["intervals"] or any("potential_safe" not in i["counts"] for i in summary["intervals"]):
        errors.append("Missing complete schema-2 diagnostic intervals.")
    pipeline = summary["pipeline_interval_totals"]
    if any(pipeline.get(k, 0) for k in ("pending", "failed", "fallback", "inconsistent")):
        errors.append("Experimental pipeline pending/failure/fallback/inconsistency occurred in the window.")
    if mode == 0 and summary["reported_totals"].get("omitted", 0):
        errors.append("Default run unexpectedly omitted fragment stages.")
    if mode == 1 and not summary["reported_totals"].get("omitted", 0):
        errors.append("Experimental run did not confirm any omissions.")
    fps = []
    for line in log.read_text().splitlines():
        match = diag.FPS.search(line)
        if match:
            fps.append(match)
            if "KeyCavern" not in match[5] or float(match[4]) >= 100:
                errors.append("Non-Key-Cavern or loading/hitch FPS interval in measurement window.")
            if not re.search(r"\bcompile 0/", match[6]):
                errors.append("Shader compilation or missing compile count in the measured window; warm up longer.")
    if (len(fps) < 20 or (fps and float(fps[-1][1]) - float(fps[0][1]) < 90) or
            not summary["interval_gpu_ms_per_present_by_level"]):
        errors.append("Insufficient warmed Key Cavern timing samples.")
    return sorted(set(errors))


def comparison(results):
    errors = [f"{name}: {issue}" for name, result in results.items() for issue in result["validation_errors"]]
    if set(results) != {name for name, _ in RUNS}:
        errors.append("Both runs were not completed.")
    if len(results) == 2:
        a, b = (results[name] for name, _ in RUNS)
        for field in ("executable_sha256", "initial_settings_sha256", "route"):
            if a[field] != b[field]:
                errors.append(f"Run mismatch: {field}.")
        snapshots = [r["summary"]["output_snapshots"] for r in (a, b)]
        if all(snapshots) and (output_identity(snapshots[0][0]["text"]) != output_identity(snapshots[1][0]["text"]) or
                              snapshots[0][0]["settings"].get("upscaler") != snapshots[1][0]["settings"].get("upscaler")):
            errors.append("The two runs used different output configurations.")
        levels = [set(r["summary"]["warmed_fps_by_level"]) for r in (a, b)]
        if levels[0] != levels[1]:
            errors.append("The two runs visited different measured levels.")
    lines = ["# Fixed-Match Key Cavern depth omission A/B", "", "Comparable timing windows: " + ("NO" if errors else "YES"), "",
             "Human visual assessment is required; synthetic tests do not prove gameplay correctness.", ""]
    for name, result in results.items():
        s = result["summary"]
        lines += [f"## {name}", "", f"Visual check: {result['visual_check']}", "", "```json",
                  json.dumps({"counts": s["reported_totals"], "fps": s["warmed_fps_by_level"],
                              "gpu_ms_per_present_proxy": s["interval_gpu_ms_per_present_by_level"]}, indent=2), "```", ""]
    if not errors:
        for level in sorted(levels[0]):
            av = a["summary"]["interval_gpu_ms_per_present_by_level"].get(level, {}).get("median")
            bv = b["summary"]["interval_gpu_ms_per_present_by_level"].get(level, {}).get("median")
            if av and bv is not None:
                lines += [f"{level}: GPU/present proxy median {av:.3f} → {bv:.3f} ms ({100 * (av - bv) / av:.1f}% reduction).", ""]
    lines += ["## Limitations / invalidation", ""] + ["- " + issue for issue in errors]
    lines += ["", "Counts omit the first straddling and final partial intervals. Timing drops ten seconds after a level's first log.",
              "GPU completion counters are asynchronous proxies. Repeat in reverse order after cooling; compare GPU time and tails, not just FPS.",
              "Default pacing/synchronization/preparation remain active. A 30 FPS cap does not by itself establish no GPU improvement."]
    return "\n".join(lines) + "\n"


def archive_results(out):
    archive = out.with_suffix(".zip")
    names = ["manifest.json", "COMPARISON.md"]
    names += [f"{name}/{file}" for name, _ in RUNS for file in ("run.log", "measurement.log", "summary.json")]
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as dest:
        for name in names:
            if (out / name).is_file():
                dest.write(out / name, f"{out.name}/{name}")
    return archive


def wait_normally(process):
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            print("Quit the game normally. Private saves remain available until it exits.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("data-root", "settings", "save-dir"):
        parser.add_argument("--" + flag)
    parser.add_argument("--drawable", default="2880x1800", help="Expected actual drawable; default 2880x1800, reduced display typically 2048x1280")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    exe = diag.ROOT / "build/lasrecomp"
    if sys.platform != "darwin" or not exe.is_file() or not os.access(exe, os.X_OK):
        parser.error("Requires macOS and the existing compiled development executable.")
    if not re.fullmatch(r"\d+x\d+", args.drawable) or args.seconds < 120:
        parser.error("Use --drawable WIDTHxHEIGHT and at least 120 seconds.")
    if b"potential_safe=" not in exe.read_bytes():
        parser.error("Build lacks schema-2 instrumentation; compile the host first.")
    try:
        root, settings, save = diag.data_paths(args)
    except ValueError as error:
        parser.error(str(error))
    if not any(p.is_file() for p in (exe.parent / "lasgame.dylib", root / "extracted/lasgame.dylib")):
        parser.error("An existing compiled game library is required. Do not generate game code during this benchmark.")
    git = lambda *parts: subprocess.check_output(["git", *parts], cwd=diag.ROOT, text=True).strip()
    manifest = {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
                "dirty": bool(git("status", "--porcelain")), "expected_drawable": args.drawable,
                "seconds": args.seconds, "reverse": args.reverse, "executable": str(exe), "runs": {}}
    print(f"Executable: {exe}\nGit: {manifest['commit']} ({manifest['branch']}), dirty={manifest['dirty']}")
    print(f"Keep macOS display settings fixed; expected Metal drawable {args.drawable}. No display setting will be changed.\n"
          "Both disposable settings copies use fullscreen, Original 16:9, Match display, AA Off, and the same upscaler.\n"
          "Quit other LAS Recomp instances. Use the same Key Cavern room/route in each run. Do not change settings,\n"
          "seed, or data folder. If asked to build game code, quit. Warm up for at least 30 seconds in the room.\n"
          "Inspect flickering, dark rectangles, missing geometry and depth artifacts in BOTH runs.")
    route = input("Describe the room and repeatable route (no personal information): ").strip()
    out = Path(tempfile.mkdtemp(prefix=f"LASRecomp-Depth-AB-{datetime.now():%Y%m%d-%H%M%S}-", dir=Path.home() / "Desktop"))
    results = manifest["runs"]
    try:
        with tempfile.TemporaryDirectory(prefix="lasrecomp-depth-ab-private-") as temporary:
            scratch = Path(temporary)
            # Freeze source inputs once, then prepare both independent runs before either child can mutate its copy.
            prepared = {}
            for name, mode in RUNS:
                folder = scratch / name; folder.mkdir()
                prepared[name] = private_run(folder, settings, save, root, mode, os.environ)
            for name, mode in (reversed(RUNS) if args.reverse else RUNS):
                input(f"{name}: Press Return to launch (Ctrl-C cancels before launch): ")
                run = out / name; run.mkdir()
                env = prepared[name]
                result = {"route": route, "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                          "initial_settings_sha256": hashlib.sha256(Path(env["LARECOMP_SETTINGS"]).read_bytes()).hexdigest(),
                          "mode": mode, "visual_check": "not checked", "exit_code": None, "validation_errors": []}
                results[name] = result
                print("Flags: " + " ".join(f"{k}={env[k]}" for k in diag.FLAGS), flush=True)
                with (run / "run.log").open("ab", buffering=0) as log:
                    process = subprocess.Popen([str(exe)], cwd=diag.ROOT, env=env, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        input("Warm up in Key Cavern, then Return here to arm the window. You have 10 seconds to refocus the game: ")
                        time.sleep(10)
                        if process.poll() is None:
                            log.write((BEGIN + "\n").encode())
                            print(f"Measuring for {args.seconds} seconds. Stay in the room and follow the agreed route.", flush=True)
                            time.sleep(args.seconds)
                            log.write((END + "\n").encode())
                            print("\aMeasurement complete. Quit LAS Recomp normally.", flush=True)
                    finally:
                        # Never terminate gameplay or delete a live process's temporary saves on cancellation/error.
                        result["exit_code"] = wait_normally(process)
                result["visual_check"] = input("Observed flickering / dark rectangles / missing geometry / depth artifacts? Type none only if all checked; otherwise describe: ").strip() or "not checked"
                errors = measurement_log(run / "run.log", run / "measurement.log")
                summary = diag.summarize(run / "measurement.log", mode, args.drawable)
                errors += validate(summary, run / "measurement.log", args.drawable, mode)
                if result["exit_code"] != 0:
                    errors.append(f"Process exit code {result['exit_code']}.")
                if result["visual_check"].lower() != "none":
                    errors.append("Visual validation incomplete or a defect was reported.")
                if not route:
                    errors.append("Room/route was not recorded.")
                result.update(summary=summary, validation_errors=sorted(set(errors)))
                (run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    except (KeyboardInterrupt, EOFError, OSError, ValueError) as error:
        manifest["collection_error"] = str(error) or type(error).__name__
        # Retain partial logs; never report an interrupted window as a valid comparison.
        for result in results.values():
            if "summary" not in result:
                result["summary"] = diag.summarize_empty()
                result["validation_errors"].append("Collection interrupted before analysis.")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "COMPARISON.md").write_text(comparison(results))
    archive = archive_results(out)
    print(f"Results: {archive}", flush=True)
    subprocess.run(["open", "-R", str(archive)], check=False)
    return 0 if len(results) == 2 and all(not r["validation_errors"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
