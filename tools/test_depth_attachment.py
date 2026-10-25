"""Test production attachment proof under ASan/UBSan with synthetic data only."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as directory:
    exe = Path(directory) / "depth-attachment-test"
    subprocess.run(shlex.split(os.environ.get("CC", "clang")) +
                   ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "tools/test_depth_attachment.c", "-o", str(exe)], cwd=ROOT, check=True)
    subprocess.run([str(exe)], check=True)
