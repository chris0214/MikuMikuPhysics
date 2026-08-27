"""Dump mmd_type distribution after importing the test PMX model."""
import os
import sys
from collections import Counter

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner

root_name = blender_runner.import_test_model()
root = bpy.data.objects[root_name]
counter = Counter()
for obj in root.children_recursive:
    try:
        counter[obj.mmd_type] += 1
    except Exception:
        counter["<none>"] += 1
print("MMD_TYPE_COUNTS", dict(counter))
print("ROOT_NAME", root_name, "children", len(root.children))
arm = next((c for c in root.children_recursive if c.type == "ARMATURE"), None)
print("ARMATURE", arm.name if arm else None)
rigid_parent = [c for c in root.children if c.mmd_type not in ("", "ROOT")]
for c in rigid_parent[:10]:
    print("CHILD", c.name, c.mmd_type, len(c.children))
