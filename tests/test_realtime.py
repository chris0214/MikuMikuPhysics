"""Realtime controller tests: start physics, drive TimerController.tick manually.

Blender's background mode never fires ``bpy.app.timers`` callbacks (no event
loop), so the harness calls ``tick()`` directly to exercise the realtime code
path used by the GUI timer in foreground Blender.
"""

import os
import sys
import unittest

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner  # noqa: E402


class RealtimeController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_name = blender_runner.import_test_model()
        import MikuMikuPhysics

        MikuMikuPhysics.register()
        cls.addon = MikuMikuPhysics

    @classmethod
    def tearDownClass(cls):
        from MikuMikuPhysics.physics import physics_sync

        physics_sync.force_stop()
        cls.addon.unregister()

    def test_start_and_manual_ticks(self):
        from MikuMikuPhysics.physics import physics_sync

        settings = bpy.context.scene.pmx_physics
        root = bpy.data.objects[self.root_name]
        settings.model_root = root
        result = bpy.ops.pmx_physics.start()
        self.assertEqual(result, {"FINISHED"})
        self.assertTrue(physics_sync.is_active())

        controller = physics_sync._controller
        self.assertIsNotNone(controller)
        for _ in range(120):
            returned = controller.tick()
            if returned is None:
                self.fail("tick stopped the simulation unexpectedly")

        physics_sync.force_stop()
        self.assertFalse(physics_sync.is_active())

    def test_timeline_mode_frame_change(self):
        from MikuMikuPhysics.physics import physics_sync

        settings = bpy.context.scene.pmx_physics
        root = bpy.data.objects[self.root_name]
        settings.model_root = root
        settings.timeline_mode = True
        try:
            result = bpy.ops.pmx_physics.start()
            self.assertEqual(result, {"FINISHED"})
            controller = physics_sync._controller
            scene = bpy.context.scene
            for frame in range(2, 6):
                scene.frame_set(frame)
                controller.frame_change(scene)
            physics_sync.force_stop()
        finally:
            settings.timeline_mode = False


if __name__ == "__main__":
    unittest.main()
