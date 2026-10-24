"""Production diagnostic classification and accounting under ASan/UBSan; no game files."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as directory:
    exe = Path(directory) / "depth-diag-test"
    subprocess.run(shlex.split(os.environ.get("CC", "clang")) +
                   ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "tools/test_depth_no_fs_diag.c", "-o", str(exe)], cwd=ROOT, check=True)
    subprocess.run([str(exe)], check=True)
