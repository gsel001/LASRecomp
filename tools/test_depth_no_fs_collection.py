"""Synthetic log analysis, scratch-save isolation and end-to-end collection; never launches LAS Recomp."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import depth_no_fs_diagnostic as collect

SAMPLE = """[depth-no-fs] experimental=1 (synthetic)
[depth-no-fs-diag] enabled=1 experimental=1 schema=1 (observer only)
[depth-no-fs-diag] frame 300 interval 6.0s attempts=8 evaluated=6 eligible_evaluated=2 total=5 depth_bound=5 depth_only=4 probe_potential=3 entered=5 certified=2 eligible=2 omitted=1
[depth-no-fs-diag] rejected(first; completed draws): color_bound=1 stencil=2
[depth-no-fs-diag] probe_potential_rejected(first; subset of completed draws): stencil=1
[depth-no-fs-diag] depth_only_reasons(overlap): stencil=2 depth_view=2
[depth-no-fs-diag] pipeline(interval encounters): pending=1 failed=0 fallback=1 inconsistent=0
[depth-no-fs-diag] skipped(interval): pre_no_program=0 pre_program_not_ready=2 pre_other=0 post_pipeline=1 post_other=0 (pre_program subsets: missing_fs=2 instruction_unknown=0)
[depth-no-fs-diag] builds(cumulative live): requested=1 ok=1 failed=0 outstanding=0
[depth-no-fs-diag] shader_translations(cumulative): total=3 msl_ok=3 certified=2
[depth-no-fs-diag] shader_cert_rejected(first; cumulative translations): cert_version=1
[depth-no-fs-diag] output frame 300 drawable 2048x1280 scale 1.067x1.067 allocation 1.067x1.067 source_texture 2048x1152 fullscreen=1 aspect=1 resolution=0 aa=0 upscaler=1
[scale] frame 0 drawable 2048x1280 -> render scale 1.067x1.067 (reshape 0)
[settings] synthetic
[pace] period 33.33 blocked 1 busy 2 cost 2 ms (queue wait 0, cpu 4.60, render cpu 2, gpu 16.82, gpu wait 0)
[pace] period 70.0 blocked 1 busy 2 cost 2 ms (queue wait 0, cpu 14.60, render cpu 2, gpu 96.82, gpu wait 0) (no gameplay)
[metal] t=10.0 frame 300 30.0 fps max 34ms level Lv03KeyCavern (1 draws, gpu 300ms, compile 0/0ms)
[metal] t=20.0 frame 600 30.0 fps max 34ms level Lv03KeyCavern (1 draws, gpu 600ms, compile 0/0ms)
"""


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = self.root / "run.log"

    def summary(self, text=SAMPLE):
        self.log.write_text(text)
        return collect.summarize(self.log)

    def test_valid_accounting_and_cumulative_not_summed(self):
        summary = self.summary(SAMPLE + SAMPLE)
        self.assertEqual(summary["reported_totals"]["total"], 10)
        self.assertEqual(summary["rejected_first"], {"color_bound": 2, "stencil": 4})
        self.assertEqual(summary["pipeline_builds_cumulative_latest"]["live"]["requested"], 1)
        self.assertFalse(any("mismatch" in x for x in summary["warnings"]))

    def test_sample_pair_counter_names(self):
        summary = self.summary(SAMPLE.replace("omitted=1\n", "omitted=1 raw0_metal1=4 potential_raw0_metal1=3\n"))
        self.assertEqual(summary["reported_totals"]["raw0_metal1"], 4)
        self.assertEqual(summary["reported_totals"]["potential_raw0_metal1"], 3)

    def test_gameplay_gpu_excludes_non_gameplay(self):
        summary = self.summary()
        self.assertEqual(summary["gameplay_pace_gpu_delta_ms"]["samples"], 1)
        self.assertEqual(summary["gameplay_pace_gpu_delta_ms"]["median"], 16.82)
        self.assertEqual(summary["gameplay_cpu_ms"]["median"], 4.6)

    def test_interval_timing_and_level_warmup(self):
        summary = self.summary()
        self.assertEqual(summary["warmed_fps_by_level"]["Lv03KeyCavern"]["samples"], 1)
        self.assertEqual(summary["interval_gpu_ms_per_present_by_level"]["Lv03KeyCavern"]["median"], 2)

    def test_missing_instrumentation_is_not_zero_measurement(self):
        summary = self.summary("[depth-no-fs] experimental=1\n[depth-no-fs] frame 300 completed=100 omitted=0\n")
        self.assertEqual(summary["reported_totals"], {})
        self.assertFalse(summary["diagnostics_enabled"])
        self.assertTrue(any("No diagnostic intervals" in x for x in summary["warnings"]))

    def test_incomplete_diagnostic_block(self):
        summary = self.summary(SAMPLE.replace("[depth-no-fs-diag] rejected(first; completed draws): color_bound=1 stencil=2\n", ""))
        self.assertTrue(any("Incomplete" in x for x in summary["warnings"]))

    def test_reconciliation_errors_detected(self):
        summary = self.summary(SAMPLE.replace("total=5 ", "total=7 ").replace("attempts=8 ", "attempts=12 "))
        self.assertTrue(any("Completed-draw accounting mismatch" in x for x in summary["warnings"]))
        self.assertTrue(any("Pre-eligibility accounting mismatch" in x for x in summary["warnings"]))
        self.assertTrue(any("Post-eligibility accounting mismatch" in x for x in summary["warnings"]))

    def test_wrong_resolution_and_settings_warn(self):
        summary = self.summary(SAMPLE.replace("drawable 2048x1280", "drawable 2880x1800").replace("aa=0", "aa=1"))
        self.assertTrue(any("Final drawable differs" in x for x in summary["warnings"]))
        self.assertTrue(any("Final actual fullscreen" in x for x in summary["warnings"]))

    def test_inconsistency_and_inactive_switch_warn(self):
        summary = self.summary(SAMPLE.replace("experimental=1", "experimental=0").replace("inconsistent=0", "inconsistent=1"))
        self.assertTrue(any("Experimental=1" in x for x in summary["warnings"]))
        self.assertTrue(any("inconsistency" in x for x in summary["warnings"]))

    def test_private_settings_saves_and_environment(self):
        settings = self.root / "settings.ini"
        settings.write_text("aspect = original\n")
        save = self.root / "source-save"
        save.mkdir(); (save / "synthetic").write_text("original")
        scratch = self.root / "private"; scratch.mkdir()
        env, private = collect.prepare_private_run(scratch, settings, save, self.root,
                                                  {"LARECOMP_NO_SYNC": "1", "LARECOMP_WARP": "unsafe", "PATH": "x"})
        (Path(env["LARECOMP_SAVE_DIR"]) / "synthetic").write_text("modified private")
        private.write_text("modified private")
        self.assertEqual(settings.read_text(), "aspect = original\n")
        self.assertEqual((save / "synthetic").read_text(), "original")
        self.assertNotIn("LARECOMP_NO_SYNC", env)
        self.assertNotIn("LARECOMP_WARP", env)
        self.assertEqual(env["LARECOMP_DEPTH_NO_FS_DIAG"], "1")
        self.assertEqual(env["PATH"], "x")

    def test_save_symlink_rejected(self):
        settings = self.root / "settings.ini"; settings.write_text("")
        save = self.root / "save"; save.mkdir()
        (save / "link").symlink_to(settings)
        scratch = self.root / "scratch"; scratch.mkdir()
        with self.assertRaises(ValueError):
            collect.prepare_private_run(scratch, settings, save, self.root, {})

    def test_archive_allowlist(self):
        out = self.root / "result"; out.mkdir()
        for name in ("run.log", "manifest.json", "summary.json", "REPORT.md", "larecomp.ini", "lasgame.dylib", "save"):
            (out / name).write_text("synthetic")
        with zipfile.ZipFile(collect.archive_results(out)) as archive:
            self.assertEqual({Path(name).name for name in archive.namelist()}, {"run.log", "manifest.json", "summary.json", "REPORT.md"})

    def test_report_handles_absent_log(self):
        report = collect.report_text(collect.summarize_empty())
        self.assertIn("No process log", report)
        self.assertIn("Missing run.log", report)

    def full_collection(self, exit_code):
        (self.root / "Desktop").mkdir()
        (self.root / "build").mkdir()
        (self.root / "build/lasgame.dylib").write_text("synthetic placeholder, not game code")
        settings = self.root / "larecomp.ini"
        settings.write_text("aspect = original\nantialias = off\n")
        save = self.root / "save"; save.mkdir(); (save / "synthetic").write_text("original")
        exe = self.root / "build/lasrecomp"
        exe.write_text(f"#!{sys.executable}\nimport os\nfrom pathlib import Path\nprint({SAMPLE!r})\n"
                       "Path(os.environ['LARECOMP_SAVE_DIR'], 'synthetic').write_text('private changed')\n"
                       "Path(os.environ['LARECOMP_SETTINGS']).write_text('aspect = original\\n')\n"
                       f"raise SystemExit({exit_code})\n")
        exe.chmod(0o700)

        def fake_git(args, **kwargs):
            return "0" * 40 + "\n" if args[1] == "rev-parse" else "synthetic-branch\n" if args[1] == "branch" else ""

        with patch.object(collect, "ROOT", self.root), patch.object(collect.sys, "platform", "darwin"), \
             patch.object(collect.Path, "home", return_value=self.root), \
             patch.object(sys, "argv", ["diagnostic", "--data-root", str(self.root)]), \
             patch("builtins.input", return_value=""), patch.object(collect.subprocess, "check_output", side_effect=fake_git), \
             patch.object(collect.subprocess, "run") as finder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(collect.main(), 0 if exit_code == 0 else 1)
        archives = list((self.root / "Desktop").glob("*.zip"))
        self.assertEqual(len(archives), 1)
        finder.assert_called_once_with(["open", "-R", str(archives[0])], check=False)
        with zipfile.ZipFile(archives[0]) as archive:
            summary_name = next(x for x in archive.namelist() if x.endswith("summary.json"))
            summary = json.loads(archive.read(summary_name))
            self.assertEqual(summary["reported_totals"]["total"], 5)
            self.assertTrue(all(Path(x).suffix in (".log", ".json", ".md") for x in archive.namelist()))
        self.assertEqual(settings.read_text(), "aspect = original\nantialias = off\n")
        self.assertEqual((save / "synthetic").read_text(), "original")

    def test_full_collection_with_fake_process(self):
        self.full_collection(0)

    def test_failed_process_preserves_logs_and_archive(self):
        self.full_collection(7)


if __name__ == "__main__":
    unittest.main()
