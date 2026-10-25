"""Synthetic fixed-window analysis and data isolation; never launches gameplay."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import depth_no_fs_ab as ab
import depth_no_fs_diagnostic as diag

OUTPUT = ("[depth-no-fs-diag] output frame 0 drawable 2880x1800 scale 1.500x1.500 allocation 1.500x1.500 "
          "source_texture 2880x1620 fullscreen=1 aspect=1 resolution=0 aa=0 upscaler=1\n")
SCALE = "[scale] frame 0 drawable 2880x1800 -> render scale 1.500x1.500 (reshape 0)\n"


def block(mode, total=10):
    return (f"[depth-no-fs-diag] frame 600 interval 6.0s attempts={total} evaluated={total} total={total} "
            f"eligible={total * mode} omitted={total * mode} probe_potential={total} potential_safe={total}\n"
            f"[depth-no-fs-diag] rejected(first; completed draws): {'none' if mode else f'switch_off={total}'}\n"
            f"[depth-no-fs-diag] probe_potential_rejected(first; subset of completed draws): {'none' if mode else f'switch_off={total}'}\n"
            "[depth-no-fs-diag] depth_only_reasons(overlap): none\n"
            "[depth-no-fs-diag] pipeline(interval encounters): pending=0 failed=0 fallback=0 inconsistent=0\n"
            "[depth-no-fs-diag] skipped(interval): pre_no_program=0 pre_program_not_ready=0 pre_other=0 post_pipeline=0 post_other=0\n"
            "[depth-no-fs-diag] shader_cert_reasons(overlap; cumulative translations): none\n")


def capture(mode):
    timing = "".join(f"[metal] t={10 + i * 3}.0 frame {300 + i * 90} 30.0 fps max 34ms level Lv03KeyCavern "
                     "(1 draws, gpu 1350ms, compile 0/0ms)\n" for i in range(40))
    return (f"[depth-no-fs] experimental={mode}\n[depth-no-fs-diag] enabled=1 schema=2\n" + OUTPUT + SCALE +
            ab.BEGIN + "\n" + block(mode, 999) + timing + OUTPUT + block(mode) + ab.END + "\n" + block(mode, 999))


class ABTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw, self.window = self.root / "run.log", self.root / "measurement.log"

    def analyze(self, mode=1, text=None):
        self.raw.write_text(capture(mode) if text is None else text)
        errors = ab.measurement_log(self.raw, self.window)
        summary = diag.summarize(self.window, mode, "2880x1800")
        return summary, errors + ab.validate(summary, self.window, "2880x1800", mode)

    def test_complete_default_and_experiment_windows(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                summary, errors = self.analyze(mode)
                self.assertEqual(errors, [])
                self.assertEqual(summary["reported_totals"]["total"], 10)
                self.assertEqual(summary["reported_totals"]["omitted"], mode * 10)
                self.assertEqual(summary["reported_totals"]["potential_safe"], 10)

    def test_missing_end_invalidates_window(self):
        _, errors = self.analyze(text=capture(1).replace(ab.END, "missing"))
        self.assertTrue(any("boundaries" in e for e in errors))

    def test_return_to_match_does_not_hide_drift(self):
        text = capture(1).replace(ab.END, OUTPUT.replace("resolution=0", "resolution=1") + OUTPUT + ab.END)
        _, errors = self.analyze(text=text)
        self.assertTrue(any("not fullscreen/Original/Match" in e for e in errors))

    def test_between_snapshot_scale_change_detected(self):
        text = capture(1).replace(ab.END, "[scale] frame 3 drawable 2880x1800 -> render scale 1.000x1.000\n" + ab.END)
        _, errors = self.analyze(text=text)
        self.assertTrue(any("scale change" in e for e in errors))

    def test_wrong_drawable(self):
        _, errors = self.analyze(text=capture(1).replace("2880x1800", "2048x1280"))
        self.assertTrue(any("drawable" in e for e in errors))

    def test_incomplete_final_diagnostic_excluded(self):
        self.raw.write_text(capture(1).replace(ab.END, "[depth-no-fs-diag] frame 999 total=123\n" + ab.END))
        errors = ab.measurement_log(self.raw, self.window)
        self.assertTrue(any("Incomplete diagnostic" in e for e in errors))
        self.assertEqual(diag.summarize(self.window)["reported_totals"]["total"], 10)

    def test_interleaved_output_is_not_counted_twice(self):
        self.raw.write_text(capture(1).replace("[depth-no-fs-diag] skipped(interval)", OUTPUT + "[depth-no-fs-diag] skipped(interval)"))
        ab.measurement_log(self.raw, self.window)
        # One pre-window anchor, one ordinary output and one interleaved output in each of the two window blocks.
        self.assertEqual(self.window.read_text().count("[depth-no-fs-diag] output "), 4)

    def test_compile_fallback_and_missing_omissions(self):
        for text, expected in ((capture(1).replace("compile 0/", "compile 1/"), "compilation"),
                               (capture(1).replace("fallback=0", "fallback=1"), "pipeline"),
                               (capture(1).replace("omitted=10", "omitted=0"), "any omissions"),
                               (capture(1).replace("potential_safe=10", "old_schema=10"), "schema-2")):
            with self.subTest(expected=expected):
                _, errors = self.analyze(text=text)
                self.assertTrue(any(expected in e for e in errors))

    def test_mixed_location_rejected(self):
        _, errors = self.analyze(text=capture(1).replace("level Lv03KeyCavern", "level Field", 1))
        self.assertTrue(any("Non-Key-Cavern" in e for e in errors))

    def test_independent_saves_and_private_settings(self):
        settings, save = self.root / "larecomp.ini", self.root / "save"
        settings.write_text("resolution = 1\nupscaler = bilinear\nfullscreen = 0\n")
        save.mkdir(); (save / "synthetic").write_text("original")
        runs = []
        for name, mode in ab.RUNS:
            folder = self.root / name; folder.mkdir()
            runs.append(ab.private_run(folder, settings, save, self.root, mode, {"LARECOMP_NO_SYNC": "1"}))
        for env, mode in zip(runs, (0, 1)):
            values = diag.ini_values(Path(env["LARECOMP_SETTINGS"]))
            self.assertEqual(values["resolution"], "match")
            self.assertEqual(values["upscaler"], "bilinear")
            self.assertEqual(env["LARECOMP_DEPTH_NO_FS"], str(mode))
            self.assertNotIn("LARECOMP_NO_SYNC", env)
        (Path(runs[0]["LARECOMP_SAVE_DIR"]) / "synthetic").write_text("private A changed")
        self.assertEqual((Path(runs[1]["LARECOMP_SAVE_DIR"]) / "synthetic").read_text(), "original")
        self.assertEqual((save / "synthetic").read_text(), "original")
        self.assertEqual(diag.ini_values(settings)["resolution"], "1")

    def test_archive_is_allowlisted_including_partial_run(self):
        out = self.root / "result"; out.mkdir()
        (out / "manifest.json").write_text(json.dumps({"synthetic": True}))
        run = out / "A-default"; run.mkdir()
        for file in ("run.log", "save", "larecomp.ini", "lasgame.dylib"):
            (run / file).write_text("synthetic placeholder")
        with zipfile.ZipFile(ab.archive_results(out)) as z:
            self.assertEqual(set(z.namelist()), {"result/manifest.json", "result/A-default/run.log"})

    def test_comparison_does_not_claim_incomplete_pair(self):
        self.assertIn("Comparable timing windows: NO", ab.comparison({}))

    def collection(self, exit_code):
        (self.root / "Desktop").mkdir()
        (self.root / "build").mkdir()
        exe = self.root / "build/lasrecomp"
        exe.write_text("synthetic executable marker potential_safe="); exe.chmod(0o700)
        (self.root / "build/lasgame.dylib").write_text("synthetic placeholder")
        settings, save = self.root / "larecomp.ini", self.root / "save"
        settings.write_text("resolution = 1\nupscaler = bilinear\n")
        save.mkdir(); (save / "synthetic").write_text("original")
        active = {}

        class FakeProcess:
            def __init__(self, *args, env, stdout, **kwargs):
                mode = int(env["LARECOMP_DEPTH_NO_FS"])
                self.log, self.mode = stdout, mode
                before = capture(mode).split(ab.BEGIN)[0]
                stdout.write(before.encode())
                active["process"] = self
                private = Path(env["LARECOMP_SAVE_DIR"]) / "synthetic"
                if private.read_text() != "original":
                    raise AssertionError("Run started from another run's mutated save")
                private.write_text("private changed")

            def poll(self):
                return None

            def wait(self):
                return exit_code

        def tick(seconds):
            if seconds == 120:
                p = active["process"]
                p.log.write(capture(p.mode).split(ab.BEGIN + "\n")[1].split(ab.END)[0].encode())

        def prompt(text):
            return "none" if text.startswith("Observed") else "synthetic room/route" if text.startswith("Describe") else ""

        with patch.object(diag, "ROOT", self.root), patch.object(ab.sys, "platform", "darwin"), \
             patch.object(Path, "home", return_value=self.root), \
             patch.object(ab.sys, "argv", ["ab", "--data-root", str(self.root)]), \
             patch("builtins.input", side_effect=prompt), patch.object(ab.time, "sleep", side_effect=tick), \
             patch.object(ab.subprocess, "check_output", return_value="synthetic-git"), \
             patch.object(ab.subprocess, "Popen", side_effect=FakeProcess), \
             patch.object(ab.subprocess, "run") as finder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ab.main(), 0 if exit_code == 0 else 1)
        archive = next((self.root / "Desktop").glob("*.zip"))
        finder.assert_called_once_with(["open", "-R", str(archive)], check=False)
        with zipfile.ZipFile(archive) as z:
            report = z.read(next(n for n in z.namelist() if n.endswith("COMPARISON.md"))).decode()
            self.assertIn("Comparable timing windows: " + ("YES" if exit_code == 0 else "NO"), report)
            self.assertEqual(sum(n.endswith("run.log") for n in z.namelist()), 2)
        self.assertEqual((save / "synthetic").read_text(), "original")
        self.assertEqual(diag.ini_values(settings)["resolution"], "1")

    def test_two_run_collection_and_finder_without_gameplay(self):
        self.collection(0)

    def test_failed_process_preserves_both_logs_and_invalidates_pair(self):
        self.collection(7)


if __name__ == "__main__":
    unittest.main()
