import time

import bpy

from .physics_world import PhysicsWorld, capture_initial_snapshot, restore_last_initial_snapshot
from .hybrid_physics_world import HybridPhysicsWorld
from .shared_physics_world import SharedPhysicsWorld
from .shadow_physics_world import ShadowPhysicsWorld
from .types import MODE_STATIC


_controller = None
_REGISTRY_KEY = "pmx_physics.controllers"
_RIGIDBODY_DISABLE_KEY = "pmx_physics.rigidbody_disable_state"


def _controller_registry():
    registry = bpy.app.driver_namespace.get(_REGISTRY_KEY)
    if not isinstance(registry, list):
        registry = []
        bpy.app.driver_namespace[_REGISTRY_KEY] = registry
    return registry


def _known_controllers():
    controllers = []
    seen = set()
    if _controller is not None:
        controllers.append(_controller)
        seen.add(id(_controller))
    for controller in list(_controller_registry()):
        if id(controller) in seen:
            continue
        controllers.append(controller)
        seen.add(id(controller))
    return controllers


def _is_animation_playing():
    try:
        screen = bpy.context.screen
    except Exception:
        screen = None
    return bool(getattr(screen, "is_animation_playing", False))


def _register_controller(controller):
    registry = _controller_registry()
    if all(item is not controller for item in registry):
        registry.append(controller)


def _unregister_controller(controller):
    registry = _controller_registry()
    registry[:] = [
        item
        for item in registry
        if item is not controller and bool(getattr(item, "running", False))
    ]


def _clear_current_controller(controller):
    global _controller
    if _controller is controller:
        _controller = None


def _active_model_roots(settings):
    roots = []
    seen = set()
    for item in getattr(settings, "model_roots", []):
        root = getattr(item, "root", None)
        if root is None or not bool(getattr(item, "enabled", True)):
            continue
        key = root.name
        if key in seen:
            continue
        roots.append(root)
        seen.add(key)
    return roots


def _disable_blender_rigidbody_world(scene):
    rigidbody_world = getattr(scene, "rigidbody_world", None)
    if rigidbody_world is None:
        return None, None
    namespace = bpy.app.driver_namespace
    state = namespace.get(_RIGIDBODY_DISABLE_KEY)
    if not isinstance(state, dict) or state.get("world_id") != id(rigidbody_world):
        state = {
            "world_id": id(rigidbody_world),
            "previous_enabled": bool(rigidbody_world.enabled),
            "count": 0,
        }
    state["count"] = int(state.get("count", 0)) + 1
    namespace[_RIGIDBODY_DISABLE_KEY] = state
    rigidbody_world.enabled = False
    return rigidbody_world, state.get("previous_enabled")


def _restore_blender_rigidbody_world(rigidbody_world, previous_enabled):
    if rigidbody_world is None:
        return
    namespace = bpy.app.driver_namespace
    state = namespace.get(_RIGIDBODY_DISABLE_KEY)
    if not isinstance(state, dict) or state.get("world_id") != id(rigidbody_world):
        if previous_enabled is not None:
            rigidbody_world.enabled = previous_enabled
        return

    count = max(0, int(state.get("count", 0)) - 1)
    if count > 0:
        state["count"] = count
        namespace[_RIGIDBODY_DISABLE_KEY] = state
        return

    rigidbody_world.enabled = bool(state.get("previous_enabled", previous_enabled))
    namespace.pop(_RIGIDBODY_DISABLE_KEY, None)


def is_active():
    return any(bool(getattr(controller, "running", False)) for controller in _known_controllers())


def _time_scale(settings):
    return max(0.0, float(getattr(settings, "time_scale", 1.0)))


def _fixed_timestep(settings):
    resolver = getattr(settings, "effective_fixed_timestep", None)
    if resolver is not None:
        return float(resolver())
    return float(settings.fixed_timestep)


def _effective_gravity(settings):
    resolver = getattr(settings, "effective_gravity", None)
    if resolver is not None:
        return resolver()
    scale = float(getattr(settings, "gravity_scale", 1.0))
    return tuple(float(value) * scale for value in settings.gravity)


def _publish_performance(settings, world):
    show_perf = bool(getattr(settings, "show_performance_stats", False))
    show_interaction = bool(getattr(settings, "show_interaction_debug", False))
    if not show_perf and not show_interaction:
        return
    perf = getattr(world, "performance", None)
    if not isinstance(perf, dict):
        return
    settings.perf_body_count = int(perf.get("body_count", 0))
    settings.perf_joint_count = int(perf.get("joint_count", 0))
    settings.perf_pair_count = int(perf.get("pair_count", 0))
    settings.perf_last_step_ms = float(perf.get("last_step_ms", 0.0))
    settings.perf_avg_step_ms = float(perf.get("avg_step_ms", 0.0))
    settings.perf_max_step_ms = float(perf.get("max_step_ms", 0.0))
    settings.perf_step_count = int(perf.get("step_count", 0))
    settings.perf_last_tick_ms = float(perf.get("last_tick_ms", 0.0))
    settings.perf_avg_tick_ms = float(perf.get("avg_tick_ms", 0.0))
    settings.perf_max_tick_ms = float(perf.get("max_tick_ms", 0.0))
    settings.perf_last_flush_ms = float(perf.get("last_flush_ms", 0.0))
    settings.perf_avg_flush_ms = float(perf.get("avg_flush_ms", 0.0))
    settings.perf_max_flush_ms = float(perf.get("max_flush_ms", 0.0))
    settings.perf_last_collect_ms = float(perf.get("last_collect_ms", 0.0))
    settings.perf_avg_collect_ms = float(perf.get("avg_collect_ms", 0.0))
    settings.perf_max_collect_ms = float(perf.get("max_collect_ms", 0.0))
    settings.perf_last_native_ms = float(perf.get("last_native_ms", 0.0))
    settings.perf_avg_native_ms = float(perf.get("avg_native_ms", 0.0))
    settings.perf_max_native_ms = float(perf.get("max_native_ms", 0.0))
    settings.perf_last_readback_ms = float(perf.get("last_readback_ms", 0.0))
    settings.perf_avg_readback_ms = float(perf.get("avg_readback_ms", 0.0))
    settings.perf_max_readback_ms = float(perf.get("max_readback_ms", 0.0))
    settings.perf_last_apply_ms = float(perf.get("last_apply_ms", 0.0))
    settings.perf_avg_apply_ms = float(perf.get("avg_apply_ms", 0.0))
    settings.perf_max_apply_ms = float(perf.get("max_apply_ms", 0.0))
    settings.perf_last_tick_steps = int(perf.get("last_tick_steps", 0))
    settings.perf_last_smoothing_segments = int(perf.get("last_smoothing_segments", 1))
    settings.perf_max_smoothing_segments = int(perf.get("max_smoothing_segments", 1))
    settings.perf_last_bone_writes = int(perf.get("last_bone_writes", 0))
    settings.perf_last_object_writes = int(perf.get("last_object_writes", 0))
    settings.perf_last_contact_pairs = int(perf.get("last_contact_pairs", 0))
    settings.perf_last_shared_active_models = int(perf.get("last_shared_active_models", 0))
    settings.perf_last_changed_models = int(perf.get("last_changed_models", 0))
    settings.perf_last_contact_models = int(perf.get("last_contact_models", 0))
    settings.perf_last_disabled_model_pairs = int(perf.get("last_disabled_model_pairs", 0))
    settings.perf_last_writeback_models = int(perf.get("last_writeback_models", 0))
    settings.perf_last_contact_detect_ms = float(perf.get("last_contact_detect_ms", 0.0))
    settings.interaction_debug_static_count = int(perf.get("interaction_static_scope_count", 0))
    settings.interaction_debug_dynamic_count = int(perf.get("interaction_dynamic_scope_count", 0))
    settings.interaction_debug_frozen_count = int(perf.get("interaction_frozen_dynamic_count", 0))
    settings.interaction_debug_static_bodies = str(perf.get("interaction_static_bodies", ""))
    settings.interaction_debug_dynamic_bodies = str(perf.get("interaction_dynamic_bodies", ""))
    settings.interaction_debug_written_bones = str(perf.get("interaction_written_bones", ""))


def _publish_all_performance(settings):
    show_perf = bool(getattr(settings, "show_performance_stats", False))
    show_interaction = bool(getattr(settings, "show_interaction_debug", False))
    if not show_perf and not show_interaction:
        return
    controllers = [controller for controller in _known_controllers() if bool(getattr(controller, "running", False))]
    if len(controllers) <= 1:
        if controllers:
            _publish_performance(settings, controllers[0].world)
        return

    perfs = []
    for controller in controllers:
        perf = getattr(getattr(controller, "world", None), "performance", None)
        if isinstance(perf, dict):
            perfs.append(perf)
    if not perfs:
        return

    def total(key):
        return sum(float(perf.get(key, 0.0)) for perf in perfs)

    def maximum(key):
        return max(float(perf.get(key, 0.0)) for perf in perfs)

    settings.perf_body_count = sum(int(perf.get("body_count", 0)) for perf in perfs)
    settings.perf_joint_count = sum(int(perf.get("joint_count", 0)) for perf in perfs)
    settings.perf_pair_count = sum(int(perf.get("pair_count", 0)) for perf in perfs)
    settings.perf_last_step_ms = total("last_step_ms")
    settings.perf_avg_step_ms = total("avg_step_ms")
    settings.perf_max_step_ms = total("max_step_ms")
    settings.perf_step_count = sum(int(perf.get("step_count", 0)) for perf in perfs)
    settings.perf_last_tick_ms = total("last_tick_ms")
    settings.perf_avg_tick_ms = total("avg_tick_ms")
    settings.perf_max_tick_ms = total("max_tick_ms")
    settings.perf_last_flush_ms = total("last_flush_ms")
    settings.perf_avg_flush_ms = total("avg_flush_ms")
    settings.perf_max_flush_ms = total("max_flush_ms")
    settings.perf_last_collect_ms = total("last_collect_ms")
    settings.perf_avg_collect_ms = total("avg_collect_ms")
    settings.perf_max_collect_ms = total("max_collect_ms")
    settings.perf_last_native_ms = total("last_native_ms")
    settings.perf_avg_native_ms = total("avg_native_ms")
    settings.perf_max_native_ms = total("max_native_ms")
    settings.perf_last_readback_ms = total("last_readback_ms")
    settings.perf_avg_readback_ms = total("avg_readback_ms")
    settings.perf_max_readback_ms = total("max_readback_ms")
    settings.perf_last_apply_ms = total("last_apply_ms")
    settings.perf_avg_apply_ms = total("avg_apply_ms")
    settings.perf_max_apply_ms = total("max_apply_ms")
    settings.perf_last_tick_steps = sum(int(perf.get("last_tick_steps", 0)) for perf in perfs)
    settings.perf_last_smoothing_segments = int(maximum("last_smoothing_segments"))
    settings.perf_max_smoothing_segments = int(maximum("max_smoothing_segments"))
    settings.perf_last_bone_writes = sum(int(perf.get("last_bone_writes", 0)) for perf in perfs)
    settings.perf_last_object_writes = sum(int(perf.get("last_object_writes", 0)) for perf in perfs)
    settings.perf_last_contact_pairs = sum(int(perf.get("last_contact_pairs", 0)) for perf in perfs)
    settings.perf_last_shared_active_models = sum(int(perf.get("last_shared_active_models", 0)) for perf in perfs)
    settings.perf_last_changed_models = sum(int(perf.get("last_changed_models", 0)) for perf in perfs)
    settings.perf_last_contact_models = sum(int(perf.get("last_contact_models", 0)) for perf in perfs)
    settings.perf_last_disabled_model_pairs = sum(int(perf.get("last_disabled_model_pairs", 0)) for perf in perfs)
    settings.perf_last_writeback_models = sum(int(perf.get("last_writeback_models", 0)) for perf in perfs)
    settings.perf_last_contact_detect_ms = total("last_contact_detect_ms")
    settings.interaction_debug_static_count = sum(int(perf.get("interaction_static_scope_count", 0)) for perf in perfs)
    settings.interaction_debug_dynamic_count = sum(int(perf.get("interaction_dynamic_scope_count", 0)) for perf in perfs)
    settings.interaction_debug_frozen_count = sum(int(perf.get("interaction_frozen_dynamic_count", 0)) for perf in perfs)
    static_bodies = []
    dynamic_bodies = []
    for perf in perfs:
        text = str(perf.get("interaction_static_bodies", ""))
        if text:
            static_bodies.append(text)
        text = str(perf.get("interaction_dynamic_bodies", ""))
        if text:
            dynamic_bodies.append(text)
    settings.interaction_debug_static_bodies = " | ".join(static_bodies)[:240]
    settings.interaction_debug_dynamic_bodies = " | ".join(dynamic_bodies)[:240]
    written = []
    for perf in perfs:
        text = str(perf.get("interaction_written_bones", ""))
        if text:
            written.append(text)
    settings.interaction_debug_written_bones = " | ".join(written)[:240]


def _scene_fps(scene):
    fps_base = float(getattr(scene.render, "fps_base", 1.0))
    if fps_base <= 0.0:
        fps_base = 1.0
    return max(1.0, float(getattr(scene.render, "fps", 30)) / fps_base)


def _scene_frame_start(scene):
    return int(getattr(scene, "frame_start", 1))


def _timeline_warmup_limit(settings):
    return max(0, min(10000, int(getattr(settings, "bake_preroll", 30))))


def _startup_sync_steps(settings):
    return max(0, min(300, int(getattr(settings, "startup_sync_steps", 30))))


def _realtime_apply_options(settings):
    return {
        "update_rigid_objects": bool(getattr(settings, "realtime_update_rigid_objects", False)),
        "skip_unchanged_bones": bool(getattr(settings, "realtime_skip_unchanged_bones", True)),
        "write_location_threshold": max(0.0, float(getattr(settings, "realtime_write_location_threshold", 0.00015))),
        "write_rotation_threshold": max(0.0, float(getattr(settings, "realtime_write_rotation_threshold", 0.02))),
        "follow_root_motion": bool(getattr(settings, "realtime_follow_root_motion", True)),
        "drag_compensation": bool(getattr(settings, "realtime_drag_compensation", True)),
        "drag_compensate_static": bool(getattr(settings, "realtime_drag_compensate_static", True)),
        "drag_compensate_dynamic_bone": bool(getattr(settings, "realtime_drag_compensate_dynamic_bone", True)),
        "drag_max_segments": max(1, int(getattr(settings, "realtime_drag_max_segments", 32))),
        "drag_resync": bool(getattr(settings, "realtime_drag_resync", True)),
        "drag_resync_threshold": max(0.01, float(getattr(settings, "realtime_drag_resync_threshold", 0.5))),
        "drag_resync_clear_velocity": bool(getattr(settings, "realtime_drag_resync_clear_velocity", False)),
    }


def _full_apply_options():
    return {
        "update_rigid_objects": True,
        "skip_unchanged_bones": False,
        "write_location_threshold": 0.0,
        "write_rotation_threshold": 0.0,
        "follow_root_motion": True,
        "drag_compensation": True,
        "drag_compensate_static": True,
        "drag_compensate_dynamic_bone": True,
        "drag_max_segments": 32,
        "drag_resync": True,
        "drag_resync_threshold": 0.5,
        "drag_resync_clear_velocity": False,
    }


def _substeps_per_frame(scene, settings):
    seconds_per_frame = 1.0 / _scene_fps(scene)
    fixed_step = _fixed_timestep(settings)
    substeps = max(1, round(seconds_per_frame / fixed_step))
    return substeps, seconds_per_frame / substeps


def _advance_frame_span(world, scene, settings, frame_delta):
    if frame_delta <= 0:
        return
    substeps_per_frame, timestep = _substeps_per_frame(scene, settings)
    for _ in range(frame_delta * substeps_per_frame):
        world.step(timestep * _time_scale(settings), 1)


def _advance_scene_frames(world, scene, settings, last_frame, target_frame):
    if target_frame <= last_frame:
        return
    for frame in range(last_frame + 1, target_frame + 1):
        if int(scene.frame_current) != frame:
            scene.frame_set(frame)
        world.flush_depsgraph()
        _advance_frame_span(world, scene, settings, 1)
        world.flush_depsgraph()


def _initialize_timeline_world(context, settings, world, root):
    scene = context.scene
    target_frame = int(scene.frame_current)
    start_frame = min(target_frame, _scene_frame_start(scene))
    root_for_snapshot = root
    if root_for_snapshot is None:
        from . import pmx_data_reader

        root_for_snapshot = pmx_data_reader.find_root_object(context.active_object)
    original_snapshot = None
    if root_for_snapshot is not None:
        from . import pmx_data_reader

        try:
            original_snapshot = capture_initial_snapshot(pmx_data_reader.read_model(context, root_for_snapshot))
        except Exception:
            original_snapshot = None

    scene.frame_set(start_frame)
    _initialize_world(context, settings, world, root, apply_options=_full_apply_options())
    if original_snapshot is not None:
        world.set_initial_snapshot(original_snapshot)

    world.flush_depsgraph()
    preroll = min(_timeline_warmup_limit(settings), max(0, target_frame - start_frame))
    if preroll > 0:
        _advance_frame_span(world, scene, settings, preroll)
        world.flush_depsgraph()

    _advance_scene_frames(world, scene, settings, start_frame, target_frame)

    if scene.frame_current != target_frame:
        scene.frame_set(target_frame)
        world.flush_depsgraph()
    _publish_performance(settings, world)


def _armature_has_action(armature):
    if armature is None:
        return False
    animation_data = getattr(armature, "animation_data", None)
    if animation_data is None:
        return False
    if animation_data.action is not None:
        return True
    return any(not track.mute and any(strip.action is not None for strip in track.strips) for track in animation_data.nla_tracks)


def _has_armature_action(world):
    models = getattr(world, "models", None)
    if models:
        return any(_armature_has_action(getattr(model, "armature", None)) for model in models)

    model = getattr(world, "model", None)
    return _armature_has_action(getattr(model, "armature", None))


def _initialize_world(context, settings, world, root, startup_sync=True, apply_options=None):
    if apply_options is None:
        apply_options = _realtime_apply_options(settings)
    world.initialize(
        context,
        root,
        settings.resolved_dll_path(),
        _effective_gravity(settings),
        settings.solver_iterations,
        settings.use_frame_offset,
        settings.joint_stop_erp,
        settings.joint_stop_cfm,
        settings.locked_joint_stop_erp,
        settings.locked_joint_stop_cfm,
        settings.prewarm_steps,
        settings.kinematic_smoothing,
        settings.kinematic_smoothing_steps,
        settings.kinematic_smoothing_move,
        settings.kinematic_smoothing_angle,
        _startup_sync_steps(settings) if startup_sync else 0,
        settings.locked_joint_pullback,
        settings.resting_body_stabilization,
        apply_options,
    )
    _publish_performance(settings, world)


class TimerController:
    def __init__(self, world, settings, scene):
        self.world = world
        self.settings = settings
        self.scene = scene
        self.running = True
        self.stopped = False
        self.timer_callback = self.tick
        self.last_time = time.perf_counter()
        self.accumulator = 0.0
        self.last_frame = int(scene.frame_current)
        self.has_armature_action = _has_armature_action(world)
        self._internal_frame_set = False
        self._was_animation_playing = _is_animation_playing()
        self._interaction_snapshot = self._capture_interaction_snapshot()
        self._last_interaction_pose_bones = set()
        self._held_interaction_pose_bones = set()
        self._interaction_pose_hold_until = 0.0
        self._last_interaction_response = 0.0
        self.rigidbody_world, self.previous_rigidbody_enabled = _disable_blender_rigidbody_world(scene)
        # Idle-CPU optimization: the interaction snapshot scan copies every
        # tracked pose matrix (~240 timer wakes/sec). A depsgraph_update_post
        # flag lets tick() skip that scan when nothing in the scene changed;
        # without an update no tracked matrix can have moved, so the skipped
        # comparison would always report "no change" anyway.
        self._scene_dirty = True
        self._depsgraph_handler = self._on_depsgraph_update
        bpy.app.handlers.depsgraph_update_post.append(self._depsgraph_handler)

    def _on_depsgraph_update(self, scene, depsgraph):
        if self.running:
            self._scene_dirty = True

    def tick(self):
        if not self.running:
            return None

        tick_start = time.perf_counter()
        try:
            now = time.perf_counter()
            elapsed = max(0.0, min(now - self.last_time, 0.25))
            self.last_time = now
            self.accumulator += elapsed

            fixed_step = _fixed_timestep(self.settings)
            is_animation_playing = _is_animation_playing()
            if is_animation_playing != self._was_animation_playing:
                self._was_animation_playing = is_animation_playing
                self.last_frame = int(self.scene.frame_current)
                self.accumulator = 0.0
                self.world.flush_depsgraph()
                self.world.reset_to_current_pose()
                return max(0.001, fixed_step * 0.5)
            if self._sync_changed_scene_frame(fixed_step):
                return max(0.001, fixed_step * 0.5)
            interaction_kind = "NONE"
            if not is_animation_playing:
                if self._scene_dirty or self._held_interaction_pose_bones:
                    interaction_kind = self._interaction_change_kind()
                    self._configure_interaction_pose_scope(interaction_kind, now)
                    self._scene_dirty = False
                else:
                    # Nothing tracked can have changed since the last scan
                    # (no depsgraph update arrived), so skip the full pose
                    # matrix snapshot and only refresh the selection-driven
                    # fallback scope that `_interaction_change_kind` would
                    # have produced on its "no change" branch.
                    interaction_kind = self._interaction_fallback_kind()
                    self._configure_interaction_pose_scope(interaction_kind, now)
            if self._maybe_interaction_response(now, fixed_step, interaction_kind):
                _publish_all_performance(self.settings)
                return 0.001

            steps = 0
            max_steps = int(self.settings.max_substeps)
            if self.accumulator < fixed_step:
                return max(0.001, min(fixed_step * 0.5, fixed_step - self.accumulator))

            self.world.configure_apply_options(_realtime_apply_options(self.settings))
            flush_ms = 0.0
            if self.has_armature_action:
                flush_start = time.perf_counter()
                self.world.flush_depsgraph()
                flush_ms = (time.perf_counter() - flush_start) * 1000.0
            while self.accumulator >= fixed_step and steps < max_steps:
                next_steps = steps + 1
                apply_results = self.accumulator < fixed_step * 2.0 or next_steps >= max_steps
                self.world.step(fixed_step * _time_scale(self.settings), 1, apply_results=apply_results)
                self.accumulator -= fixed_step
                steps += 1
            if steps:
                if self._last_step_wrote_results():
                    flush_start = time.perf_counter()
                    self.world.flush_depsgraph()
                    flush_ms += (time.perf_counter() - flush_start) * 1000.0
                    self._interaction_snapshot = self._capture_interaction_snapshot()
                self.world.record_flush_time(flush_ms)
                self.world.record_tick_time((time.perf_counter() - tick_start) * 1000.0, steps)
                _publish_all_performance(self.settings)

            return max(0.001, fixed_step * 0.5)
        except Exception as exc:
            self.settings.status = str(exc)
            self.settings.is_running = False
            self.stop()
            return None

    def _capture_interaction_snapshot(self):
        matrices = {}
        for root in self._iter_world_roots():
            if root is None:
                continue
            matrices[f"root:{root.name}"] = root.matrix_world.copy()
            armature = self._find_armature(root)
            if armature is not None:
                matrices[f"armature:{armature.name}"] = armature.matrix_world.copy()
                for pose_bone in self._iter_interaction_pose_bones(root, armature):
                    matrices[f"pose:{armature.name}:{pose_bone.name}"] = pose_bone.matrix.copy()
        return matrices

    def _iter_world_roots(self):
        roots = getattr(self.world, "roots", None)
        if roots is not None:
            return list(roots)
        root = getattr(self.world, "root", None)
        if root is not None:
            return [root]
        worlds = getattr(self.world, "worlds", None)
        if worlds is not None:
            result = []
            for world in worlds:
                root = getattr(world, "root", None)
                if root is not None:
                    result.append(root)
            return result
        # Fallback: derive the root from `world.model`/`world.models` so
        # interaction-scope plumbing keeps working even on world classes that
        # forgot to expose `root`/`roots` directly. Without this fallback a
        # single-model PhysicsWorld would report zero roots, the scope would
        # always be empty, and user-bone selection could not constrain the
        # interaction scope.
        models = getattr(self.world, "models", None) or []
        result = []
        for model in models:
            model_root = getattr(model, "root", None)
            if model_root is not None:
                result.append(model_root)
        if result:
            return result
        model = getattr(self.world, "model", None)
        if model is not None:
            model_root = getattr(model, "root", None)
            if model_root is not None:
                return [model_root]
        return []

    def _find_armature(self, root):
        if getattr(root, "type", None) == "ARMATURE":
            return root
        for child in getattr(root, "children_recursive", []):
            if getattr(child, "type", None) == "ARMATURE":
                return child
        return None

    def _iter_interaction_pose_bones(self, root, armature):
        model = self._find_world_model(root)
        names = set()
        if model is not None:
            for rigid in getattr(model, "rigid_bodies", []):
                if getattr(rigid, "mode", None) != MODE_STATIC:
                    continue
                bone_name = getattr(rigid, "bone_name", "")
                if bone_name:
                    names.add(bone_name)

        active_bone_name = self._active_pose_bone_name(armature)
        if active_bone_name:
            names.add(active_bone_name)
        for scoped_armature, bone_name in self._selected_pose_bone_scope_for_armature(armature):
            if scoped_armature == armature.name and bone_name:
                names.add(bone_name)

        if not names and model is None:
            for pose_bone in armature.pose.bones:
                yield pose_bone
            return

        for bone_name in names:
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is not None:
                yield pose_bone

    def _find_world_model(self, root):
        model = getattr(self.world, "model", None)
        if model is not None and getattr(model, "root", None) == root:
            return model
        for model in getattr(self.world, "models", []) or []:
            if getattr(model, "root", None) == root:
                return model
        for world in getattr(self.world, "worlds", []) or []:
            model = getattr(world, "model", None)
            if model is not None and getattr(model, "root", None) == root:
                return model
        return None

    def _matrix_changed(self, previous, current):
        if previous is None:
            return True
        delta = previous.inverted_safe() @ current
        translation = delta.to_translation().length
        try:
            rotation = delta.to_quaternion().angle
        except Exception:
            rotation = 0.0
        return translation > 0.00005 or rotation > 0.0002

    def _interaction_change_kind(self):
        current = self._capture_interaction_snapshot()
        self._last_interaction_pose_bones = set()
        if set(current.keys()) != set(self._interaction_snapshot.keys()):
            changed_keys = set(current.keys()).symmetric_difference(self._interaction_snapshot.keys())
            self._interaction_snapshot = current
            if not changed_keys or any(not key.startswith("pose:") for key in changed_keys):
                return "TRANSFORM"
            filtered_scope = self._preferred_interaction_pose_scope(
                self._pose_bone_keys_to_scope(changed_keys),
                prefer_changed=False,
            )
            if filtered_scope:
                self._last_interaction_pose_bones = filtered_scope
                return "POSE"
            return "NONE"
        changed_keys = [
            key
            for key, matrix in current.items()
            if self._matrix_changed(self._interaction_snapshot.get(key), matrix)
        ]
        if changed_keys:
            self._interaction_snapshot = current
        if not changed_keys:
            fallback_scope = self._preferred_interaction_pose_scope(prefer_changed=False)
            if fallback_scope:
                self._last_interaction_pose_bones = fallback_scope
                return "POSE"
            if self._held_interaction_pose_bones:
                self._last_interaction_pose_bones = set(self._held_interaction_pose_bones)
                return "POSE"
            return "NONE"
        if any(not key.startswith("pose:") for key in changed_keys):
            return "TRANSFORM"
        changed_scope = self._pose_bone_keys_to_scope(changed_keys)
        filtered_scope = self._preferred_interaction_pose_scope(changed_scope)
        if not filtered_scope:
            return "NONE"
        self._last_interaction_pose_bones = filtered_scope
        return "POSE"

    def _interaction_fallback_kind(self):
        """Selection-driven fallback of ``_interaction_change_kind``.

        Mirrors its "no changed keys" branch exactly: with no depsgraph
        update since the last scan the matrix comparison is guaranteed to
        find no changes, so only this fallback scope remains relevant.
        """
        self._last_interaction_pose_bones = set()
        fallback_scope = self._preferred_interaction_pose_scope(prefer_changed=False)
        if fallback_scope:
            self._last_interaction_pose_bones = fallback_scope
            return "POSE"
        if self._held_interaction_pose_bones:
            self._last_interaction_pose_bones = set(self._held_interaction_pose_bones)
            return "POSE"
        return "NONE"

    def _preferred_interaction_pose_scope(self, changed_scope=None, prefer_changed=True):
        active_scope = self._filter_scope_to_input_bones(self._active_pose_bone_scope())
        changed_scope = self._filter_scope_to_input_bones(changed_scope or set())
        selected_scope = self._filter_scope_to_input_bones(self._selected_pose_bone_scope())
        # The "changed" scope is sampled from every static-bound bone's pose
        # matrix, which means parent-chain propagation (e.g. moving an arm
        # nudges the head/hip/skirt-root pose matrices by tiny amounts) would
        # leak unrelated bones into the interaction scope. Intersect with the
        # bones the user actually selected/activated so the scope only covers
        # what the user is dragging. Fall back to the raw changed set only when
        # there is no selection at all (e.g. running from a script).
        user_scope = active_scope | selected_scope
        if user_scope:
            constrained = changed_scope & user_scope if changed_scope else set()
            if prefer_changed:
                return constrained or user_scope
            return user_scope or constrained
        if prefer_changed:
            return changed_scope or active_scope or selected_scope
        return active_scope or selected_scope or changed_scope

    @staticmethod
    def _pose_bone_keys_to_scope(keys):
        scope = set()
        for key in keys:
            parts = key.split(":", 2)
            if len(parts) == 3 and parts[0] == "pose":
                scope.add((parts[1], parts[2]))
        return scope

    def _selected_pose_bone_scope(self):
        obj = getattr(bpy.context, "object", None)
        if obj is None or getattr(obj, "type", None) != "ARMATURE":
            return set()
        return self._selected_pose_bone_scope_for_armature(obj)

    def _selected_pose_bone_scope_for_armature(self, obj):
        if obj is None or getattr(obj, "type", None) != "ARMATURE":
            return set()
        known_armatures = {
            armature.name
            for root in self._iter_world_roots()
            for armature in [self._find_armature(root)]
            if armature is not None
        }
        if obj.name not in known_armatures:
            return set()

        scope = set()
        selected = getattr(bpy.context, "selected_pose_bones", None) or []
        for pose_bone in selected:
            scope.add((obj.name, pose_bone.name))

        active_bone = getattr(obj.data.bones, "active", None)
        if active_bone is not None:
            scope.add((obj.name, active_bone.name))
        return scope

    def _active_pose_bone_scope(self):
        obj = getattr(bpy.context, "object", None)
        if obj is None or getattr(obj, "type", None) != "ARMATURE":
            return set()
        if obj.name not in {
            armature.name
            for root in self._iter_world_roots()
            for armature in [self._find_armature(root)]
            if armature is not None
        }:
            return set()
        active_name = self._active_pose_bone_name(obj)
        if not active_name:
            return set()
        return {(obj.name, active_name)}

    @staticmethod
    def _active_pose_bone_name(armature):
        active = getattr(getattr(armature, "data", None), "bones", None)
        active = getattr(active, "active", None)
        if active is not None:
            return active.name
        pose_bone = getattr(bpy.context, "active_pose_bone", None)
        if pose_bone is not None and getattr(getattr(pose_bone, "id_data", None), "name", None) == armature.name:
            return pose_bone.name
        return ""

    def _filter_scope_to_input_bones(self, scope):
        if not scope:
            return set()
        result = set()
        for armature_name, bone_name in scope:
            root = self._root_for_armature_name(armature_name)
            if root is None:
                result.add((armature_name, bone_name))
                continue
            model = self._find_world_model(root)
            if model is None:
                result.add((armature_name, bone_name))
                continue
            input_names = self._interaction_input_bone_names(model)
            armature = self._find_armature(root)
            if bone_name in input_names:
                result.add((armature_name, bone_name))
                continue
            descendant = self._nearest_input_descendant(armature, bone_name, input_names)
            if descendant:
                result.add((armature_name, descendant))
        return result

    def _root_for_armature_name(self, armature_name):
        for root in self._iter_world_roots():
            armature = self._find_armature(root)
            if armature is not None and armature.name == armature_name:
                return root
        return None

    @staticmethod
    def _interaction_input_bone_names(model):
        return {
            getattr(rigid, "bone_name", "")
            for rigid in getattr(model, "rigid_bodies", [])
            if getattr(rigid, "mode", None) == MODE_STATIC and getattr(rigid, "bone_name", "")
        }

    @staticmethod
    def _bone_has_input_descendant(armature, bone_name, input_names):
        if armature is None or not input_names:
            return False
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            return False
        pending = list(pose_bone.children)
        while pending:
            child = pending.pop()
            if child.name in input_names:
                return True
            pending.extend(child.children)
        return False

    @staticmethod
    def _nearest_input_descendant(armature, bone_name, input_names):
        if armature is None or not input_names:
            return ""
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            return ""
        pending = list(pose_bone.children)
        while pending:
            next_pending = []
            for child in pending:
                if child.name in input_names:
                    return child.name
                next_pending.extend(child.children)
            pending = next_pending
        return ""

    def _configure_interaction_pose_scope(self, change_kind, now=None):
        setter = getattr(self.world, "set_interaction_pose_scope", None)
        if setter is None:
            return
        if change_kind == "POSE":
            self._held_interaction_pose_bones = set(self._last_interaction_pose_bones)
            self._interaction_pose_hold_until = (now or time.perf_counter()) + 2.0
            setter(self._held_interaction_pose_bones)
        elif self._active_pose_scope_matches_held():
            self._interaction_pose_hold_until = (now or time.perf_counter()) + 2.0
            setter(self._held_interaction_pose_bones)
        elif (
            self._held_interaction_pose_bones
            and now is not None
            and now < self._interaction_pose_hold_until
        ):
            setter(self._held_interaction_pose_bones)
        else:
            self._held_interaction_pose_bones = set()
            self._interaction_pose_hold_until = 0.0
            setter(None)
        self._publish_interaction_debug(change_kind)

    def _active_pose_scope_matches_held(self):
        if not self._held_interaction_pose_bones:
            return False
        active_scope = self._filter_scope_to_input_bones(self._active_pose_bone_scope())
        return bool(active_scope and active_scope == self._held_interaction_pose_bones)

    def _publish_interaction_debug(self, change_kind):
        if not bool(getattr(self.settings, "show_interaction_debug", False)):
            return
        self.settings.interaction_debug_kind = str(change_kind)
        if self._held_interaction_pose_bones:
            names = sorted({bone_name for _armature_name, bone_name in self._held_interaction_pose_bones})
        else:
            names = []
        self.settings.interaction_debug_scope = self._format_debug_names(names)

    @staticmethod
    def _format_debug_names(names, limit=8):
        names = [str(name) for name in names if name]
        if not names:
            return ""
        shown = names[:limit]
        suffix = f" +{len(names) - limit}" if len(names) > limit else ""
        return ", ".join(shown) + suffix

    def _maybe_interaction_response(self, now, fixed_step, change_kind=None):
        mode = getattr(self.settings, "interaction_response_mode", "OFF")
        if mode == "OFF":
            return False
        if _is_animation_playing():
            return False
        min_interval = max(0.001, float(getattr(self.settings, "interaction_response_min_interval", 0.008)))
        if now - self._last_interaction_response < min_interval:
            return False
        if change_kind is None:
            change_kind = self._interaction_change_kind()
            self._configure_interaction_pose_scope(change_kind, now)
        if change_kind == "NONE":
            return False

        response_start = time.perf_counter()
        self._last_interaction_response = now
        self.world.configure_apply_options(_realtime_apply_options(self.settings))
        flush_start = time.perf_counter()
        self.world.flush_depsgraph()
        flush_ms = (time.perf_counter() - flush_start) * 1000.0
        if change_kind == "POSE":
            sync = getattr(self.world, "sync_kinematic_only", None)
            synced = sync() if sync is not None else 0
            if mode != "IMMEDIATE":
                self.world.record_flush_time(flush_ms)
                self.world.record_tick_time((time.perf_counter() - response_start) * 1000.0, 0)
                self.settings.status = f"{bpy.app.translations.pgettext_iface('Kinematic synced')} {synced}"
                _publish_performance(self.settings, self.world)
                return False

        step_scale = max(0.05, min(1.0, float(getattr(self.settings, "interaction_response_step_scale", 0.75))))
        response_steps = 3 if mode == "IMMEDIATE" else 1
        response_timestep = fixed_step * _time_scale(self.settings) * step_scale / response_steps
        snapped = 0
        if mode == "IMMEDIATE":
            snap = getattr(self.world, "interaction_snap_dynamic_bones", None)
            if snap is not None:
                pose_bones = self._last_interaction_pose_bones if change_kind == "POSE" else None
                snapped = snap(clear_velocity=False, pose_bones=pose_bones)
        for _ in range(response_steps):
            self.world.step(response_timestep, 1, apply_results=True)
        flush_start = time.perf_counter()
        self.world.flush_depsgraph()
        flush_ms += (time.perf_counter() - flush_start) * 1000.0
        self.world.record_flush_time(flush_ms)
        self.world.record_tick_time((time.perf_counter() - response_start) * 1000.0, response_steps)
        if snapped:
            self.settings.status = f"{bpy.app.translations.pgettext_iface('Interaction snapped')} {snapped}"
        _publish_performance(self.settings, self.world)
        self._interaction_snapshot = self._capture_interaction_snapshot()
        self.accumulator = min(self.accumulator, fixed_step if mode == "IMMEDIATE" else fixed_step * 0.5)
        return True

    def _last_step_wrote_results(self):
        performance = getattr(self.world, "performance", {})
        return (
            int(performance.get("last_bone_writes", 0)) > 0
            or int(performance.get("last_object_writes", 0)) > 0
        )

    def _sync_changed_scene_frame(self, fixed_step):
        if self._internal_frame_set:
            return False
        frame = int(self.scene.frame_current)
        if frame == self.last_frame:
            return False

        frame_delta = frame - self.last_frame
        self.world.flush_depsgraph()
        if _is_animation_playing():
            self.world.reset_to_current_pose()
        elif frame_delta <= 0:
            self.world.reset_to_current_pose()
        else:
            if frame_delta > 1:
                self.settings.status = f"{frame_delta} {bpy.app.translations.pgettext_iface('frame catch-up')}"
            try:
                self._internal_frame_set = True
                _advance_scene_frames(self.world, self.scene, self.settings, self.last_frame, frame)
            finally:
                self._internal_frame_set = False

        self.last_frame = frame
        self.accumulator = 0.0
        _publish_performance(self.settings, self.world)
        _publish_all_performance(self.settings)
        return True

    def stop(self, restore_initial=False):
        if self.stopped:
            return
        self.running = False
        self.stopped = True
        try:
            handlers = bpy.app.handlers.depsgraph_update_post
            if self._depsgraph_handler in handlers:
                handlers.remove(self._depsgraph_handler)
        except Exception:
            pass
        try:
            if bpy.app.timers.is_registered(self.timer_callback):
                bpy.app.timers.unregister(self.timer_callback)
        except Exception:
            pass
        try:
            self.world.destroy(restore_initial=restore_initial)
        finally:
            _restore_blender_rigidbody_world(self.rigidbody_world, self.previous_rigidbody_enabled)
            _unregister_controller(self)
            _clear_current_controller(self)


class TimelineController:
    def __init__(self, world, settings, scene):
        self.world = world
        self.settings = settings
        self.running = True
        self.stopped = False
        self.last_frame = int(scene.frame_current)
        self.handler = self.frame_change
        self._internal_frame_set = False
        self._was_animation_playing = _is_animation_playing()
        self.rigidbody_world, self.previous_rigidbody_enabled = _disable_blender_rigidbody_world(scene)

    def frame_change(self, scene, depsgraph=None):
        if not self.running:
            return
        if self._internal_frame_set:
            return

        try:
            is_animation_playing = _is_animation_playing()
            if is_animation_playing != self._was_animation_playing:
                self._was_animation_playing = is_animation_playing
                self.world.flush_depsgraph()
                self.world.reset_to_current_pose()
                self.last_frame = int(scene.frame_current)
                return

            frame = int(scene.frame_current)
            if frame == self.last_frame:
                return
            if frame < self.last_frame:
                self.world.reset_to_current_pose()
                self.last_frame = frame
                return

            self.world.configure_apply_options(_realtime_apply_options(self.settings))
            self.world.flush_depsgraph()
            frame_delta = frame - self.last_frame
            if frame_delta > 1:
                self.settings.status = f"{frame_delta} {bpy.app.translations.pgettext_iface('frame catch-up')}"
            try:
                self._internal_frame_set = True
                _advance_scene_frames(self.world, scene, self.settings, self.last_frame, frame)
            finally:
                self._internal_frame_set = False
            _publish_performance(self.settings, self.world)

            self.last_frame = frame
        except Exception as exc:
            self.settings.status = str(exc)
            self.settings.is_running = False
            self.stop()

    def stop(self, restore_initial=False):
        if self.stopped:
            return
        self.running = False
        self.stopped = True
        handlers = bpy.app.handlers.frame_change_post
        if self.handler in handlers:
            handlers.remove(self.handler)
        try:
            self.world.destroy(restore_initial=restore_initial)
        finally:
            _restore_blender_rigidbody_world(self.rigidbody_world, self.previous_rigidbody_enabled)
            _unregister_controller(self)
            _clear_current_controller(self)


def _make_controller(context, settings, world):
    if settings.timeline_mode:
        controller = TimelineController(world, settings, context.scene)
        _register_controller(controller)
        bpy.app.handlers.frame_change_post.append(controller.handler)
        return controller

    controller = TimerController(world, settings, context.scene)
    _register_controller(controller)
    bpy.app.timers.register(controller.timer_callback, first_interval=0.0)
    return controller


def _start_root(context, settings, root):
    world = PhysicsWorld()
    try:
        if settings.timeline_mode:
            _initialize_timeline_world(context, settings, world, root)
        else:
            _initialize_world(context, settings, world, root)
    except Exception:
        world.destroy()
        raise
    return _make_controller(context, settings, world)


def _initialize_shared_world(context, settings, world, roots):
    world.initialize(
        context,
        roots,
        settings.resolved_dll_path(),
        _effective_gravity(settings),
        settings.solver_iterations,
        settings.use_frame_offset,
        settings.joint_stop_erp,
        settings.joint_stop_cfm,
        settings.locked_joint_stop_erp,
        settings.locked_joint_stop_cfm,
        settings.prewarm_steps,
        settings.kinematic_smoothing,
        settings.kinematic_smoothing_steps,
        settings.kinematic_smoothing_move,
        settings.kinematic_smoothing_angle,
        _startup_sync_steps(settings),
        settings.locked_joint_pullback,
        settings.resting_body_stabilization,
        _realtime_apply_options(settings),
    )
    _publish_performance(settings, world)


def _start_shared_roots(context, settings, roots):
    world = SharedPhysicsWorld()
    try:
        _initialize_shared_world(context, settings, world, roots)
    except Exception:
        world.destroy()
        raise
    return _make_controller(context, settings, world)


def _start_shadow_roots(context, settings, roots):
    world = ShadowPhysicsWorld()
    try:
        _initialize_shared_world(context, settings, world, roots)
    except Exception:
        world.destroy()
        raise
    return _make_controller(context, settings, world)


def _start_hybrid_roots(context, settings, roots, allow_shared_island=False):
    world = HybridPhysicsWorld(allow_shared_island=allow_shared_island)
    try:
        _initialize_shared_world(context, settings, world, roots)
    except Exception:
        world.destroy()
        raise
    return _make_controller(context, settings, world)


def _start_contact_gate_roots(context, settings, roots):
    world = SharedPhysicsWorld()
    world.configure_contact_gate(True)
    try:
        _initialize_shared_world(context, settings, world, roots)
    except Exception:
        world.destroy()
        raise
    return _make_controller(context, settings, world)


def start(context, settings):
    global _controller
    force_stop()
    root = settings.model_root
    if root is None:
        from . import pmx_data_reader

        root = pmx_data_reader.find_root_object(context.active_object)
    _controller = _start_root(context, settings, root)


def start_all(context, settings):
    global _controller
    roots = _active_model_roots(settings)
    if not roots:
        from . import pmx_data_reader

        root = settings.model_root or pmx_data_reader.find_root_object(context.active_object)
        if root is not None:
            roots = [root]
    if not roots:
        raise RuntimeError(bpy.app.translations.pgettext_iface("No mmd_tools model root selected"))

    force_stop()
    mode = getattr(settings, "multi_model_mode", "INDEPENDENT")
    if mode in {"ROOT_ISOLATED", "INDEPENDENT"}:
        _controller = _start_hybrid_roots(context, settings, roots, allow_shared_island=False)
        return len(roots)
    if mode == "SHARED_COLLISION":
        _controller = _start_shadow_roots(context, settings, roots)
        return len(roots)
    if mode == "GLOBAL_SHARED":
        _controller = _start_shared_roots(context, settings, roots)
        return len(roots)

    started = []
    try:
        for root in roots:
            started.append(_start_root(context, settings, root))
    except Exception:
        for controller in started:
            controller.stop()
            controller.settings.is_running = False
        raise
    _controller = started[0] if started else None
    return len(started)


def stop():
    return force_stop()


def reset(context, settings):
    controllers = _known_controllers()
    if not controllers:
        settings.is_running = False
        return restore_last_initial_snapshot(getattr(context, "view_layer", None))

    for controller in controllers:
        controller.stop(restore_initial=True)
        controller.settings.is_running = False
    settings.is_running = False
    return True


def force_stop():
    count = 0
    for controller in _known_controllers():
        if bool(getattr(controller, "running", False)):
            count += 1
        controller.stop()
        controller.settings.is_running = False
    _controller_registry()[:] = []
    return count


def step_once(context, settings):
    controllers = _known_controllers()
    controller = controllers[0] if controllers else None
    if controller is None:
        world = PhysicsWorld()
        root = settings.model_root
        if root is None:
            from . import pmx_data_reader

            root = pmx_data_reader.find_root_object(context.active_object)
        try:
            _initialize_world(context, settings, world, root, startup_sync=False)
            world.flush_depsgraph()
            world.step(_fixed_timestep(settings) * _time_scale(settings), settings.max_substeps)
            world.flush_depsgraph()
            _publish_performance(settings, world)
        finally:
            world.destroy()
    else:
        controller.world.flush_depsgraph()
        previous_options = controller.world.apply_options.copy()
        try:
            controller.world.configure_apply_options(_full_apply_options())
            controller.world.step(_fixed_timestep(settings) * _time_scale(settings), settings.max_substeps)
        finally:
            controller.world.apply_options = previous_options
        controller.world.flush_depsgraph()
        _publish_performance(settings, controller.world)
