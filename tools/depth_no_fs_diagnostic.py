#!/usr/bin/env python3
"""Manually played Metal diagnostic session. Standard library only; never builds or automates gameplay."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
FLAGS = {"LARECOMP_DEPTH_NO_FS": "1", "LARECOMP_DEPTH_NO_FS_DIAG": "1",
         "LARECOMP_DEPTH_PROBE": "1", "LARECOMP_LOG_PACE": "1", "LARECOMP_LOG_INTERVAL": "1"}
NUMBERS = re.compile(r"\b([a-z][a-z0-9_]*)=(\d+)\b")
FPS = re.compile(r"\[metal\] t=([\d.]+) frame (\d+) ([\d.]+) fps max ([\d.]+)ms level (.*?) \((.*)\)")


def numbers(line):
    return {key: int(value) for key, value in NUMBERS.findall(line)}


def metrics(samples):
    if not samples:
        return {"samples": 0}
    values = sorted(samples)
    return {"samples": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
            "p95_sample": values[math.ceil(len(values) * .95) - 1]}


def summarize(log, expected_experimental=1, expected_drawable="2048x1280"):
    """Only run.log is authoritative. Never consult an installed app's log or invent missing counters."""
    intervals, outputs, scale_lines, settings_lines, builds = [], [], [], [], {}
    fps = defaultdict(list)
    gpu_intervals = defaultdict(list)
    pace_gpu, pace_period, pace_cpu = [], [], []
    current, previous, level_since = None, None, 0.0
    enabled, experimental = False, None
    translations, shader_first = None, None
    with Path(log).open(errors="replace") as source:
        for line_number, line in enumerate(source, 1):
            if line.startswith("[depth-no-fs] experimental="):
                experimental = numbers(line).get("experimental")
            if line.startswith("[depth-no-fs-diag] enabled=1"):
                enabled = True
            if line.startswith("[depth-no-fs-diag] frame "):
                current = {"line": line_number, "counts": numbers(line)}
                intervals.append(current)
            elif line.startswith("[depth-no-fs-diag] rejected(first;") and current is not None:
                current["first"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] probe_potential_rejected(first;") and current is not None:
                current["potential_first"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] depth_only_reasons(overlap)") and current is not None:
                current["overlap"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] pipeline(interval") and current is not None:
                current["pipeline"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] skipped(interval") and current is not None:
                current["skipped"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] builds(cumulative"):
                builds["preparation" if "cumulative preparation" in line else "live"] = numbers(line)
            elif line.startswith("[depth-no-fs-diag] shader_translations(cumulative)"):
                translations = numbers(line)
            elif line.startswith("[depth-no-fs-diag] shader_cert_rejected(first;"):
                shader_first = numbers(line)
            elif line.startswith("[depth-no-fs-diag] output "):
                outputs.append({"line": line_number, "text": line.strip(), "settings": numbers(line)})
            if line.startswith("[scale]"):
                scale_lines.append(line.strip())
            if line.startswith("[settings]"):
                settings_lines.append(line.strip())
            if line.startswith("[pace] period ") and "(no gameplay)" not in line:
                period = re.search(r"period ([\d.]+)", line)
                gpu = re.search(r", gpu (-?[\d.]+),", line)
                cpu = re.search(r", cpu ([\d.]+),", line)
                if period:
                    pace_period.append(float(period[1]))
                if gpu and float(gpu[1]) >= 0:
                    pace_gpu.append(float(gpu[1]))
                if cpu:
                    pace_cpu.append(float(cpu[1]))
            match = FPS.search(line)
            if match:
                t, frame, rate, gap, level, stats = match.groups()
                t, frame, rate, gap = float(t), int(frame), float(rate), float(gap)
                if previous is None or level != previous[2]:
                    level_since = t
                # Exclude the first ten seconds in a level and intervals with loading-sized present gaps.
                if level != "-" and t - level_since >= 10 and gap < 100:
                    fps[level].append(rate)
                    gpu = re.search(r"\bgpu ([\d.]+)ms,", stats)
                    compile_count = re.search(r"\bcompile (\d+)/", stats)
                    if previous and frame > previous[1] and gpu and compile_count and int(compile_count[1]) == 0:
                        gpu_intervals[level].append(float(gpu[1]) / (frame - previous[1]))
                previous = (t, frame, level)
    warnings = []
    if not enabled:
        warnings.append("Missing diagnostic enabled banner: executable may lack the new instrumentation.")
    if experimental != expected_experimental:
        warnings.append(f"Experimental={expected_experimental} was not confirmed in this process output.")
    if not intervals:
        warnings.append("No diagnostic intervals; no rejection or omission measurements available.")
    sums, first, potential_first, overlap, pipeline = Counter(), Counter(), Counter(), Counter(), Counter()
    for interval in intervals:
        c = interval["counts"]
        sums.update(c)
        first.update(interval.get("first", {}))
        potential_first.update(interval.get("potential_first", {}))
        overlap.update(interval.get("overlap", {}))
        pipeline.update(interval.get("pipeline", {}))
        if not {"first", "potential_first", "pipeline", "skipped", "overlap"}.issubset(interval):
            warnings.append(f"Incomplete diagnostic block at log line {interval['line']}.")
        if "total" not in c or "eligible" not in c or "first" not in interval:
            warnings.append(f"Missing accounting fields at log line {interval['line']}.")
            continue
        if c["total"] != c["eligible"] + sum(interval["first"].values()):
            warnings.append(f"Completed-draw accounting mismatch at log line {interval['line']}.")
        skipped = interval.get("skipped", {})
        if {"attempts", "evaluated"}.issubset(c) and {"pre_no_program", "pre_program_not_ready", "pre_other"}.issubset(skipped):
            if c["attempts"] != c["evaluated"] + sum(skipped[k] for k in ("pre_no_program", "pre_program_not_ready", "pre_other")):
                warnings.append(f"Pre-eligibility accounting mismatch at log line {interval['line']}.")
        if {"post_pipeline", "post_other"}.issubset(skipped) and "evaluated" in c:
            if c["evaluated"] != c["total"] + skipped["post_pipeline"] + skipped["post_other"]:
                warnings.append(f"Post-eligibility accounting mismatch at log line {interval['line']}.")
        if interval.get("pipeline", {}).get("inconsistent", 0):
            warnings.append(f"Observer/selector inconsistency at log line {interval['line']}.")
    if not outputs:
        warnings.append("No actual drawable/settings snapshots available.")
    else:
        final = outputs[-1]
        if f"drawable {expected_drawable} " not in final["text"]:
            warnings.append(f"Final drawable differs from the expected {expected_drawable}; consult output snapshots.")
        expected = {"fullscreen": 1, "aspect": 1, "resolution": 0, "aa": 0}
        if any(final["settings"].get(k) != v for k, v in expected.items()):
            warnings.append("Final actual fullscreen/aspect/resolution/AA differs from the requested settings.")
    if not any("KeyCavern" in level for level in fps):
        warnings.append("No warmed Key Cavern FPS samples identified; menus/loads are not a benchmark.")
    warnings.append("Final partial diagnostic interval is not flushed at exit; totals cover reported intervals only.")
    return {"experimental": experimental, "diagnostics_enabled": enabled, "intervals": intervals,
            "reported_totals": dict(sums), "rejected_first": dict(first), "probe_potential_rejected_first": dict(potential_first),
            "depth_only_reasons_overlap": dict(overlap), "pipeline_interval_totals": dict(pipeline),
            "pipeline_builds_cumulative_latest": builds, "shader_translations_cumulative_latest": translations,
            "shader_cert_rejected_cumulative_latest": shader_first, "output_snapshots": outputs,
            "scale_changes": scale_lines, "settings_log": settings_lines,
            "warmed_fps_by_level": {k: metrics(v) for k, v in fps.items()},
            "interval_gpu_ms_per_present_by_level": {k: metrics(v) for k, v in gpu_intervals.items()},
            "gameplay_pace_gpu_delta_ms": metrics(pace_gpu), "gameplay_period_ms": metrics(pace_period),
            "gameplay_cpu_ms": metrics(pace_cpu), "warnings": warnings,
            "timing_limit": "GPU counters arrive asynchronously. Pace deltas and interval GPU/present are proxies, not exact per-frame GPU percentiles."}


def ini_values(path):
    values = {}
    for line in path.read_text(errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith(("#", ";")):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def data_paths(args):
    app_home = Path(os.environ.get("LARECOMP_DATA_HOME", Path.home() / "Library/Application Support/com.peiikai.lasrecomp"))
    if args.data_root or os.environ.get("LARECOMP_DATA_ROOT"):
        root = Path(args.data_root or os.environ["LARECOMP_DATA_ROOT"]).expanduser().resolve()
    elif (ROOT / "extracted").is_dir():
        root = ROOT
    else:
        pointer = app_home / "data_root.txt"
        root = Path(pointer.read_text().splitlines()[0]) if pointer.is_file() and pointer.read_text().strip() else app_home
        root = root.expanduser().resolve()
    settings = Path(args.settings or os.environ.get("LARECOMP_SETTINGS", root / "larecomp.ini")).expanduser()
    if not settings.is_absolute():
        settings = root / settings
    if not root.is_dir() or not settings.is_file():
        raise ValueError("Data folder/settings not found; specify --data-root and/or --settings.")
    values = ini_values(settings)
    seed = values.get("rando_seed", "")
    if seed and (Path(seed).name != seed or seed in (".", "..")):
        raise ValueError("Unrecognized seed path; select vanilla before collecting diagnostics.")
    save = Path(args.save_dir or os.environ.get("LARECOMP_SAVE_DIR", root / "rando" / seed / "save" if seed else root / "save")).expanduser()
    if not save.is_absolute():
        save = root / save
    return root, settings.resolve(), save.resolve()


def prepare_private_run(scratch, settings, save, data_root, parent_env):
    private_settings = scratch / "larecomp.ini"
    private_save = scratch / "save"
    shutil.copyfile(settings, private_settings)
    if save.exists():
        # Refuse links rather than accidentally copying an unrelated tree; originals are always read-only inputs.
        if not save.is_dir() or any(p.is_symlink() for p in save.rglob("*")):
            raise ValueError("Save source must be a directory without symbolic links.")
        shutil.copytree(save, private_save)
    else:
        private_save.mkdir()
    env = {k: v for k, v in parent_env.items() if not k.startswith("LARECOMP_")}
    env.update(FLAGS)
    env.update({"LARECOMP_DATA_ROOT": str(data_root), "LARECOMP_SETTINGS": str(private_settings),
                "LARECOMP_SAVE_DIR": str(private_save)})
    return env, private_settings


def archive_results(out):
    # Explicit allowlist: no save/settings snapshots, binaries, shader text, game libraries or other folder contents.
    archive = out.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as result:
        for name in ("run.log", "manifest.json", "summary.json", "REPORT.md"):
            path = out / name
            if path.is_file():
                result.write(path, f"{out.name}/{name}")
    return archive


def report_text(summary):
    lines = ["# Metal depth omission rejection diagnostics", "", "Only run.log from the development process is authoritative.", "",
             "## Reported draw totals", "", "```json", json.dumps(summary["reported_totals"], indent=2), "```", "",
             "## First rejection among probe potential candidates", "", "```json",
             json.dumps(summary["probe_potential_rejected_first"], indent=2), "```", "",
             "## All completed draws: first rejections", "", "```json", json.dumps(summary.get("rejected_first", {}), indent=2), "```", "",
             "## Depth-only reasons (overlapping)", "", "```json", json.dumps(summary.get("depth_only_reasons_overlap", {}), indent=2), "```", "",
             "## Pipeline encounters / latest cumulative builds", "", "```json",
             json.dumps({"interval_totals": summary.get("pipeline_interval_totals", {}),
                         "builds_cumulative": summary.get("pipeline_builds_cumulative_latest", {})}, indent=2), "```", "",
             "## Latest cumulative shader certification events", "", "```json",
             json.dumps({"translations": summary.get("shader_translations_cumulative_latest"),
                         "rejected_first": summary.get("shader_cert_rejected_cumulative_latest")}, indent=2), "```", "",
             "## Warmed FPS by level", "", "```json", json.dumps(summary["warmed_fps_by_level"], indent=2), "```", "",
             "## GPU milliseconds per present (periodic interval proxy)", "", "```json",
             json.dumps(summary["interval_gpu_ms_per_present_by_level"], indent=2), "```", "", summary["timing_limit"], "",
             "## Actual output snapshots", ""]
    lines.extend("- " + item["text"] for item in summary["output_snapshots"])
    lines.extend(["", "## Warnings", ""])
    lines.extend("- " + warning for warning in summary["warnings"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root")
    parser.add_argument("--settings")
    parser.add_argument("--save-dir")
    args = parser.parse_args()
    exe = ROOT / "build/lasrecomp"
    if sys.platform != "darwin" or not exe.is_file() or not os.access(exe, os.X_OK):
        parser.error("Requires macOS and the compiled build/lasrecomp development executable.")
    if b"[depth-no-fs-diag]" not in exe.read_bytes():
        parser.error("Development executable lacks diagnostics. Build with make -j6 build/lasrecomp first.")
    try:
        root, settings, save = data_paths(args)
    except ValueError as error:
        parser.error(str(error))
    if not any(path.is_file() for path in (exe.parent / "lasgame.dylib", root / "extracted/lasgame.dylib")):
        parser.error("An existing compiled game library is required. This helper does not build game code.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip() != ""
    print(f"Executable: {exe}\nGit: {commit} ({branch}), uncommitted changes: {dirty}", flush=True)
    print("Active diagnostics: " + " ".join(f"{k}={v}" for k, v in FLAGS.items()), flush=True)
    print("Manually choose macOS 1024 x 640 before starting (expected drawable about 2048 x 1280).\n"
          "In the game choose fullscreen, Original 16:9, Match display, SMAA Off.\n"
          "Quit other LAS Recomp instances. Use the same Key Cavern room/route, warm up, then play for\n"
          "about two minutes and quit normally. If setup requests a game-code build, quit instead.\n"
          "Original settings/saves are protected by private temporary copies. Do not import/rebuild game files,\n"
          "switch seeds, or change the data folder during this diagnostic run.\n"
          "No macOS setting is changed by this script. No installed-app log will be copied.", flush=True)
    input("Press Return when ready to launch the development executable (Ctrl-C cancels): ")
    out = Path(tempfile.mkdtemp(prefix=f"LASRecomp-Depth-Diag-{datetime.now():%Y%m%d-%H%M%S}-", dir=Path.home() / "Desktop"))
    manifest = {"executable": str(exe), "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                "git_commit": commit, "branch": branch, "dirty": dirty, "diagnostics": FLAGS,
                "settings_sha256": hashlib.sha256(settings.read_bytes()).hexdigest(),
                "requested_macOS_mode": "1024x640 (manual, not verified by script)",
                "requested_settings": {"fullscreen": 1, "aspect": "original", "resolution": "match", "antialias": "off"},
                "started": datetime.now().astimezone().isoformat(), "logs": "run.log is complete stdout+stderr of this child process only"}
    code, error = None, None
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="lasrecomp-depth-diag-private-") as scratch_name:
        try:
            env, private_settings = prepare_private_run(Path(scratch_name), settings, save, root, os.environ)
            graphics = ("fullscreen", "aspect", "resolution", "antialias", "upscaler")
            manifest["initial_settings_file_values"] = {k: v for k, v in ini_values(private_settings).items() if k in graphics}
            with (out / "run.log").open("wb") as log:
                with subprocess.Popen([str(exe)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as process:
                    print(f"Recording PID {process.pid} to {out / 'run.log'}. Quit the game normally when finished.", flush=True)
                    # Ctrl-C is not sent to the child session; keep the private save alive until normal exit.
                    while True:
                        try:
                            code = process.wait()
                            break
                        except KeyboardInterrupt:
                            print("Still collecting. Quit LAS Recomp normally; temporary saves will stay protected until it exits.", flush=True)
            manifest["final_settings_file_values"] = {k: v for k, v in ini_values(private_settings).items() if k in graphics}
        except (OSError, ValueError) as exception:
            error = str(exception)
    manifest.update({"exit_code": code, "elapsed_seconds": round(time.monotonic() - start, 2), "collection_error": error})
    summary = summarize(out / "run.log") if (out / "run.log").exists() else summarize_empty()
    if code != 0:
        summary["warnings"].append(f"Development process did not exit successfully (exit={code}, collection error={error}).")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "REPORT.md").write_text(report_text(summary))
    archive = archive_results(out)
    print(f"Results: {archive}", flush=True)
    for warning in summary["warnings"]:
        print("WARNING: " + warning, flush=True)
    subprocess.run(["open", "-R", str(archive)], check=False)
    return 0 if code == 0 else 1


def summarize_empty():
    return {"reported_totals": {}, "probe_potential_rejected_first": {}, "warmed_fps_by_level": {},
            "interval_gpu_ms_per_present_by_level": {}, "output_snapshots": [],
            "timing_limit": "No process log was captured.", "warnings": ["Missing run.log; no measurements available."]}


if __name__ == "__main__":
    raise SystemExit(main())
