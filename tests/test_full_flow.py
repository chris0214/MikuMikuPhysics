"""Full-flow baseline test: register, import, scan and bake on the current Blender.

This is the "red" test for Blender 5.2 compatibility — run the exact user
workflow in background mode and let any API break surface as a test failure.
"""

import os
import sys
import unittest

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner  # noqa: E402  (shares sys.path setup and PMX import)


class FullFlowBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_name = blender_runner.import_test_model()
        import MikuMikuPhysics

        MikuMikuPhysics.register()
        cls.addon = MikuMikuPhysics

    @classmethod
    def tearDownClass(cls):
        cls.addon.unregister()

    def settings(self):
        return bpy.context.scene.pmx_physics

    def test_a_register_and_scan(self):
        settings = self.settings()
        root = bpy.data.objects[self.root_name]
        settings.model_root = root
        result = bpy.ops.pmx_physics.scan_model()
        self.assertEqual(result, {"FINISHED"})
        self.assertGreater(settings.perf_body_count, 0)
        self.assertGreater(settings.perf_joint_count, 0)

    def test_b_bake_small_range(self):
        settings = self.settings()
        root = bpy.data.objects[self.root_name]
        settings.model_root = root
        settings.bake_start = 1
        settings.bake_end = 5
        settings.bake_preroll = 2
        result = bpy.ops.pmx_physics.bake()
        self.assertEqual(result, {"FINISHED"})
        armature = next(
            child for child in root.children_recursive if child.type == "ARMATURE"
        )
        animation = armature.animation_data
        self.assertIsNotNone(animation)
        self.assertIsNotNone(animation.action)


if __name__ == "__main__":
    unittest.main()
