"""Bake progress reporting tests (status-bar progress bar)."""

import os
import sys
import unittest

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner  # noqa: E402


class BakeProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_name = blender_runner.import_test_model()
        import MikuMikuPhysics

        MikuMikuPhysics.register()
        cls.addon = MikuMikuPhysics

    @classmethod
    def tearDownClass(cls):
        cls.addon.unregister()

    def _settings(self):
        settings = bpy.context.scene.pmx_physics
        settings.model_root = bpy.data.objects[self.root_name]
        return settings

    def test_bake_reports_monotonic_progress_to_total(self):
        from MikuMikuPhysics.physics import bake

        settings = self._settings()
        settings.bake_start = 1
        settings.bake_end = 4
        settings.bake_preroll = 2
        events = []

        def record(done, total, frame):
            events.append((done, total, frame))

        bake.bake_to_keyframes(context=bpy.context, settings=settings, progress=record)

        expected_total = 2 + 4  # preroll frames + baked frames
        self.assertTrue(events, "progress callback was never invoked")
        dones = [event[0] for event in events]
        self.assertEqual(dones, sorted(dones), "progress must be non-decreasing")
        self.assertEqual(events[-1][0], expected_total)
        self.assertTrue(all(event[1] == expected_total for event in events))
        self.assertEqual(events[-1][2], 4, "final event must carry the last baked frame")

    def test_bake_without_callback_still_works(self):
        from MikuMikuPhysics.physics import bake

        settings = self._settings()
        settings.bake_start = 1
        settings.bake_end = 2
        settings.bake_preroll = 0
        count = bake.bake_to_keyframes(context=bpy.context, settings=settings)
        self.assertEqual(count, 2)

    def test_bake_frame_total_helper(self):
        from MikuMikuPhysics.physics import bake

        settings = self._settings()
        settings.bake_start = 3
        settings.bake_end = 12
        settings.bake_preroll = 7
        self.assertEqual(bake.bake_frame_total(settings), 7 + (12 - 3 + 1))

    def test_operator_bake_path_survives_window_manager_progress(self):
        settings = self._settings()
        settings.bake_start = 1
        settings.bake_end = 2
        settings.bake_preroll = 1
        result = bpy.ops.pmx_physics.bake()
        self.assertEqual(result, {"FINISHED"})


if __name__ == "__main__":
    unittest.main()
