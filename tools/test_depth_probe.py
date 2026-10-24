"""Exercise the production depth probe classifier/counters using synthetic metadata, without game files."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as directory:
    exe = Path(directory) / "depth-probe-test"
    subprocess.run(shlex.split(os.environ.get("CC", "clang")) +
                   ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "tools/test_depth_probe.c", "-o", str(exe)], cwd=ROOT, check=True)
    subprocess.run([str(exe)], check=True)
