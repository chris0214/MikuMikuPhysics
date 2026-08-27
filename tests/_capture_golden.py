"""Capture golden bake output samples for optimization equivalence checks."""

import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner

root_name = blender_runner.import_test_model()
import MikuMikuPhysics

MikuMikuPhysics.register()
from MikuMikuPhysics.physics import bake, pmx_data_reader

settings = bpy.context.scene.pmx_physics
settings.model_root = bpy.data.objects[root_name]
settings.bake_start = 1
settings.bake_end = 8
settings.bake_preroll = 3
settings.bake_restore_after = False

bake.bake_to_keyframes(bpy.context, settings)

model = pmx_data_reader.read_model(bpy.context, bpy.data.objects[root_name])
armature = model.armature
bone_names = sorted(
    {
        rigid.bone_name
        for rigid in model.rigid_bodies
        if rigid.mode != 0 and rigid.bone_name
    }
)
sampled = {}
original_frame = bpy.context.scene.frame_current
try:
    for frame in range(settings.bake_start, settings.bake_end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for bone_name in bone_names[:: max(1, len(bone_names) // 12)]:
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is None:
                continue
            matrix = pose_bone.matrix
            sampled[f"{frame}:{bone_name}"] = [round(value, 8) for row in matrix for value in row]
finally:
    bpy.context.scene.frame_set(original_frame)

fcurve_count = sum(len(fc.keyframe_points) for fc in (armature.animation_data.action.fcurves if armature.animation_data and armature.animation_data.action else []))
payload = {
    "bone_count": len(bone_names),
    "fcurve_keyframe_count": fcurve_count,
    "samples": sampled,
}
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_bake.json")
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
print("GOLDEN_WRITTEN samples=%d keys=%d" % (len(sampled), fcurve_count))
MikuMikuPhysics.unregister()
