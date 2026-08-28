"""Blender-side test harness for MikuMikuPhysics.

Run with:

    blender --background --python tests/blender_runner.py -- [test.module ...]

The harness:
  * adds the repository parent to ``sys.path`` so ``import MikuMikuPhysics`` works,
  * enables the bundled mmd_tools addon,
  * imports the test PMX model once per session,
  * discovers ``tests/test_*.py`` (or runs only the modules listed after ``--``),
  * runs them through ``unittest`` and reports a non-zero exit on failure.
"""

import os
import sys
import unittest

import bpy

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# The repository root is the addon package itself, so its parent is what
# belongs on sys.path for `import MikuMikuPhysics`.
ADDON_PARENT = os.path.dirname(REPO_DIR)
for path in (ADDON_PARENT, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

# The suite drives a real PMX model, but model files cannot be redistributed
# with the repository. Point the MMP_TEST_PMX environment variable at any
# local PMX file before running the tests.
PMX_PATH = os.environ.get("MMP_TEST_PMX", "")
if not os.path.isfile(PMX_PATH):
    raise RuntimeError(
        "MMP_TEST_PMX must point to an existing local PMX file "
        "(model files cannot be shipped with the repository)"
    )

BLENDER_CONFIG = os.path.join(
    os.environ.get("APPDATA", ""), "Blender Foundation", "Blender", "5.2"
)
# The host machine has two mmd_tools copies (extensions repo + legacy addons
# dir). Loading both corrupts Object.mmd_type registration, so the harness
# pins exactly one copy, preferring the extensions repository version.
MMD_TOOLS_CANDIDATES = (
    os.path.join(BLENDER_CONFIG, "extensions", "blender_org", "mmd_tools"),
    os.path.join(BLENDER_CONFIG, "scripts", "addons", "mmd_tools"),
)

_STATE = {"model_imported": False, "root_name": None}


def _extract_wheels(wheels_dir):
    """Extract bundled wheels to a temp dir (zipimport cannot serve data files)."""
    import tempfile
    import zipfile

    target = os.path.join(tempfile.gettempdir(), "mmp_test_wheels")
    os.makedirs(target, exist_ok=True)
    marker = os.path.join(target, ".extracted")
    if os.path.isfile(marker):
        if target not in sys.path:
            sys.path.insert(0, target)
        return
    for name in sorted(os.listdir(wheels_dir)):
        if name.endswith(".whl"):
            with zipfile.ZipFile(os.path.join(wheels_dir, name)) as archive:
                archive.extractall(target)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write("ok")
    if target not in sys.path:
        sys.path.insert(0, target)


def _load_single_mmd_tools():
    for candidate in MMD_TOOLS_CANDIDATES:
        if not os.path.isfile(os.path.join(candidate, "__init__.py")):
            continue
        wheels_dir = os.path.join(candidate, "wheels")
        if os.path.isdir(wheels_dir):
            _extract_wheels(wheels_dir)
        sys.modules.pop("mmd_tools", None)
        parent = os.path.dirname(candidate)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        import mmd_tools

        if not hasattr(bpy.types.Object, "mmd_type"):
            mmd_tools.register()
        return
    raise RuntimeError("no mmd_tools installation found for tests")


def import_test_model():
    """Import the shared test PMX model once per Blender session."""
    if _STATE["model_imported"]:
        return _STATE["root_name"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _load_single_mmd_tools()
    result = bpy.ops.mmd_tools.import_model(filepath=PMX_PATH, scale=0.08)
    if result == {"CANCELLED"}:
        raise RuntimeError("mmd_tools PMX import was cancelled")
    roots = [obj for obj in bpy.data.objects if getattr(obj, "mmd_type", "") == "ROOT"]
    if not roots:
        raise RuntimeError("no mmd_root object after import")
    _STATE["model_imported"] = True
    _STATE["root_name"] = roots[0].name
    return _STATE["root_name"]


def discover(requested):
    loader = unittest.TestLoader()
    if requested:
        suite = unittest.TestSuite()
        for name in requested:
            suite.addTests(loader.loadTestsFromName(name))
        return suite
    return loader.discover(TESTS_DIR, pattern="test_*.py", top_level_dir=TESTS_DIR)


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    runner = unittest.TextTestRunner(verbosity=2)
    suite = discover(argv)
    result = runner.run(suite)
    print(f"BLENDER_TESTS_RAN={result.testsRun} FAILURES={len(result.failures)} ERRORS={len(result.errors)}")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
