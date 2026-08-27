"""Throwaway profiling: measure idle tick polling cost and bake frame cost."""
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_runner

root_name = blender_runner.import_test_model()
import MikuMikuPhysics

MikuMikuPhysics.register()
from MikuMikuPhysics.physics import physics_sync, bake

settings = bpy.context.scene.pmx_physics
settings.model_root = bpy.data.objects[root_name]

# --- idle tick polling cost ---
result = bpy.ops.pmx_physics.start()
assert result == {"FINISHED"}
controller = physics_sync._controller
world = controller.world
# settle: run 60 real ticks
for _ in range(60):
    controller.tick()
# idle measurement: accumulator zeroed so tick returns before stepping
samples = []
for _ in range(300):
    controller.accumulator = 0.0
    controller.last_time = time.perf_counter()
    start = time.perf_counter()
    controller.tick()
    samples.append((time.perf_counter() - start) * 1000.0)
samples.sort()
print("IDLE_TICK_MS median=%.4f p90=%.4f mean=%.4f" % (
    samples[len(samples)//2], samples[int(len(samples)*0.9)], sum(samples)/len(samples)))
physics_sync.force_stop()

# --- bake frame cost ---
settings.bake_start = 1
settings.bake_end = 10
settings.bake_preroll = 5
start = time.perf_counter()
bake.bake_to_keyframes(bpy.context, settings)
elapsed = time.perf_counter() - start
print("BAKE_10FRAMES_S=%.3f per_frame_ms=%.1f" % (elapsed, elapsed / 15 * 1000.0))

# --- step stage breakdown ---
from MikuMikuPhysics.physics.physics_world import PhysicsWorld

world = PhysicsWorld()
world.initialize(
    bpy.context,
    bpy.data.objects[root_name],
    settings.resolved_dll_path(),
    settings.effective_gravity(),
    settings.solver_iterations,
)
try:
    for _ in range(10):
        world.step(1.0 / 120.0, 1)
    perf = world.performance
    print("STEP_MS last=%.3f avg=%.3f" % (perf["last_step_ms"], perf["avg_step_ms"]))
    print("STAGE_AVG_MS collect=%.3f native=%.3f readback=%.3f apply=%.3f" % (
        perf["avg_collect_ms"], perf["avg_native_ms"], perf["avg_readback_ms"], perf["avg_apply_ms"]))
finally:
    world.destroy()
MikuMikuPhysics.unregister()
