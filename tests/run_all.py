"""Run every Blender test module in its own Blender process.

Blender keeps session-global state (driver_namespace, cached depsgraph,
float nondeterminism across file reloads) that makes back-to-back bakes in
one process drift in the last decimals. Per-module processes keep runs
hermetic; see tests/golden_bake.json notes in the README.

Usage:
    python tests/run_all.py [BLENDER_EXE]

BLENDER_EXE defaults to the 5.2 install used for development.
"""

import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

MODULES = (
    "test_bake_progress",
    "test_full_flow",
    "test_perf",
    "test_realtime",
)


def main():
    blender = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BLENDER
    runner = os.path.join(TESTS_DIR, "blender_runner.py")
    failures = []
    for module in MODULES:
        print(f"=== {module} ===", flush=True)
        result = subprocess.run(
            [blender, "--background", "--factory-startup", "--python", runner, "--", module],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        summary = [
            line
            for line in (result.stdout + result.stderr).splitlines()
            if line.startswith(("OK", "FAILED", "BLENDER_TESTS_RAN"))
        ]
        print("\n".join(summary) or result.stdout[-2000:])
        if result.returncode != 0:
            failures.append(module)
    if failures:
        print("FAILED MODULES:", ", ".join(failures))
        sys.exit(1)
    print("ALL MODULES PASSED")


if __name__ == "__main__":
    main()
