"""Resource-usage regression tests.

* bake output must stay bit-identical to ``golden_bake.json`` (captured from
  the pre-optimization code) — optimizations may not change results,
* idle timer polling must be cheap (the controller used to re-scan every
  interaction pose matrix ~240x/s even when nothing changed),
* the kinematic collect stage must not re-invert the root matrix per rigid
  body.
"""

import json
import os
import sys
import time
import unittest

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner  # noqa: E402

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_bake.json")


class BakeEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_name = blender_runner.import_test_model()
        import MikuMikuPhysics

        MikuMikuPhysics.register()
        cls.addon = MikuMikuPhysics

    @classmethod
    def tearDownClass(cls):
        cls.addon.unregister()

    def test_bake_output_matches_golden(self):
        from MikuMikuPhysics.physics import bake, pmx_data_reader

        with open(GOLDEN_PATH, encoding="utf-8") as handle:
            golden = json.load(handle)

        settings = bpy.context.scene.pmx_physics
        settings.model_root = bpy.data.objects[self.root_name]
        settings.bake_start = 1
        settings.bake_end = 8
        settings.bake_preroll = 3
        settings.bake_restore_after = False
        bake.bake_to_keyframes(bpy.context, settings)

        model = pmx_data_reader.read_model(bpy.context, bpy.data.objects[self.root_name])
        armature = model.armature
        action = armature.animation_data.action
        keyframe_count = sum(len(fc.keyframe_points) for fc in action.fcurves)
        self.assertEqual(keyframe_count, golden["fcurve_keyframe_count"])

        original_frame = bpy.context.scene.frame_current
        try:
            for key, expected in golden["samples"].items():
                frame_text, bone_name = key.split(":", 1)
                frame = int(frame_text)
                bpy.context.scene.frame_set(frame)
                bpy.context.view_layer.update()
                pose_bone = armature.pose.bones.get(bone_name)
                self.assertIsNotNone(pose_bone, bone_name)
                actual = [round(value, 8) for row in pose_bone.matrix for value in row]
                self.assertEqual(actual, expected, f"bone matrix drifted: {key}")
        finally:
            bpy.context.scene.frame_set(original_frame)


class IdlePollingCost(unittest.TestCase):
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

    def test_idle_tick_polling_is_cheap(self):
        from MikuMikuPhysics.physics import physics_sync

        settings = bpy.context.scene.pmx_physics
        settings.model_root = bpy.data.objects[self.root_name]
        self.assertEqual(bpy.ops.pmx_physics.start(), {"FINISHED"})
        controller = physics_sync._controller
        for _ in range(60):
            controller.tick()

        if hasattr(controller, "_scene_dirty"):
            controller._scene_dirty = False
        samples = []
        for _ in range(300):
            controller.accumulator = 0.0
            controller.last_time = time.perf_counter()
            start = time.perf_counter()
            self.assertIsNotNone(controller.tick())
            samples.append((time.perf_counter() - start) * 1000.0)
        samples.sort()
        median = samples[len(samples) // 2]
        print(f"IDLE_TICK_MEDIAN_MS={median:.4f}")
        self.assertLess(
            median,
            0.4,
            "idle timer tick must not re-scan pose matrices when nothing changed",
        )


class CollectStageCost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_name = blender_runner.import_test_model()
        import MikuMikuPhysics

        MikuMikuPhysics.register()
        cls.addon = MikuMikuPhysics

    @classmethod
    def tearDownClass(cls):
        cls.addon.unregister()

    def test_collect_stage_is_cheap(self):
        from MikuMikuPhysics.physics.physics_world import PhysicsWorld

        settings = bpy.context.scene.pmx_physics
        world = PhysicsWorld()
        world.initialize(
            bpy.context,
            bpy.data.objects[self.root_name],
            settings.resolved_dll_path(),
            settings.effective_gravity(),
            settings.solver_iterations,
        )
        try:
            for _ in range(10):
                world.step(1.0 / 120.0, 1)
            avg_collect = world.performance["avg_collect_ms"]
            print(f"AVG_COLLECT_MS={avg_collect:.4f}")
            self.assertLess(avg_collect, 1.2, "kinematic collect re-inverts the root matrix too often")
        finally:
            world.destroy()


if __name__ == "__main__":
    unittest.main()
