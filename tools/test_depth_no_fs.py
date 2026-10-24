"""Exercise the production eligibility and real translator with ASan/UBSan, without game data."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as directory:
    exe = Path(directory) / "depth-no-fs-test"
    subprocess.run(shlex.split(os.environ.get("CC", "clang")) +
                   ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wno-deprecated-declarations", "-fsanitize=address,undefined",
                    "tools/test_depth_no_fs.c", "runtime/nvn/maxwell/translate.c", "-lm", "-o", str(exe)],
                   cwd=ROOT, check=True)
    subprocess.run([str(exe)], check=True)
