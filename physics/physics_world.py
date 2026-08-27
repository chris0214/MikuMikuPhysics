import math
import time

import bpy

from . import pmx_data_reader
from .bullet_native import BulletNative
from .types import MODE_DYNAMIC, MODE_DYNAMIC_BONE, MODE_STATIC

from mathutils import Matrix


_SNAPSHOT_KEY = "pmx_physics.initial_snapshot"


_PERF_STAGE_KEYS = (
    "collect_ms",
    "native_ms",
    "readback_ms",
    "apply_ms",
)


def _default_apply_options():
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


def _normalize_apply_options(options):
    normalized = _default_apply_options()
    if options:
        normalized.update(options)
    normalized["update_rigid_objects"] = bool(normalized["update_rigid_objects"])
    normalized["skip_unchanged_bones"] = bool(normalized["skip_unchanged_bones"])
    normalized["follow_root_motion"] = bool(normalized["follow_root_motion"])
    normalized["drag_compensation"] = bool(normalized["drag_compensation"])
    normalized["drag_compensate_static"] = bool(normalized["drag_compensate_static"])
    normalized["drag_compensate_dynamic_bone"] = bool(normalized["drag_compensate_dynamic_bone"])
    normalized["drag_max_segments"] = max(1, min(96, int(normalized["drag_max_segments"])))
    normalized["drag_resync"] = bool(normalized["drag_resync"])
    normalized["drag_resync_threshold"] = max(0.01, float(normalized["drag_resync_threshold"]))
    normalized["drag_resync_clear_velocity"] = bool(normalized["drag_resync_clear_velocity"])
    normalized["write_location_threshold"] = max(0.0, float(normalized["write_location_threshold"]))
    normalized["write_rotation_threshold"] = math.radians(max(0.0, float(normalized["write_rotation_threshold"])))
    return normalized


def _new_performance():
    performance = {
        "body_count": 0,
        "joint_count": 0,
        "pair_count": 0,
        "last_step_ms": 0.0,
        "avg_step_ms": 0.0,
        "max_step_ms": 0.0,
        "step_count": 0,
        "last_tick_ms": 0.0,
        "avg_tick_ms": 0.0,
        "max_tick_ms": 0.0,
        "last_flush_ms": 0.0,
        "avg_flush_ms": 0.0,
        "max_flush_ms": 0.0,
        "tick_count": 0,
        "flush_count": 0,
        "last_tick_steps": 0,
        "last_smoothing_segments": 1,
        "max_smoothing_segments": 1,
        "last_bone_writes": 0,
        "last_object_writes": 0,
        "interaction_static_scope_count": 0,
        "interaction_dynamic_scope_count": 0,
        "interaction_frozen_dynamic_count": 0,
        "interaction_static_bodies": "",
        "interaction_dynamic_bodies": "",
        "interaction_written_bones": "",
    }
    for key in _PERF_STAGE_KEYS:
        performance[f"last_{key}"] = 0.0
        performance[f"avg_{key}"] = 0.0
        performance[f"max_{key}"] = 0.0
    return performance


def _capture_object_state(obj):
    return {
        "matrix_world": obj.matrix_world.copy(),
        "matrix_basis": obj.matrix_basis.copy(),
        "matrix_parent_inverse": obj.matrix_parent_inverse.copy(),
        "location": obj.location.copy(),
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": obj.rotation_euler.copy(),
        "rotation_quaternion": obj.rotation_quaternion.copy(),
        "rotation_axis_angle": tuple(obj.rotation_axis_angle),
        "scale": obj.scale.copy(),
    }


def _restore_object_state(obj, state):
    obj.matrix_parent_inverse = state["matrix_parent_inverse"].copy()
    obj.matrix_basis = state["matrix_basis"].copy()
    obj.location = state["location"].copy()
    obj.rotation_mode = state["rotation_mode"]
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = state["rotation_quaternion"].copy()
    elif obj.rotation_mode == "AXIS_ANGLE":
        obj.rotation_axis_angle = state["rotation_axis_angle"]
    else:
        obj.rotation_euler = state["rotation_euler"].copy()
    obj.scale = state["scale"].copy()
    obj.matrix_world = state["matrix_world"].copy()


def _update_view_layer(view_layer):
    if view_layer is None:
        view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is None:
        return
    try:
        view_layer.update()
        view_layer.update()
    except RuntimeError:
        pass


def capture_initial_snapshot(model):
    snapshot = {
        "root_name": model.root.name if model.root is not None else "",
        "root_state": _capture_object_state(model.root) if model.root is not None else None,
        "armature_name": model.armature.name if model.armature is not None else "",
        "pose_basis": {},
        "constraint_mutes": [],
        "object_states": {},
    }

    armature = model.armature
    if armature is not None:
        for pose_bone in armature.pose.bones:
            snapshot["pose_basis"][pose_bone.name] = pose_bone.matrix_basis.copy()
            for constraint in pose_bone.constraints:
                if constraint.name == "mmd_tools_rigid_track":
                    snapshot["constraint_mutes"].append(
                        (armature.name, pose_bone.name, constraint.name, bool(constraint.mute))
                    )

    for rigid in model.rigid_bodies:
        obj = rigid.obj
        if obj is not None:
            snapshot["object_states"][obj.name] = _capture_object_state(obj)

    return snapshot


def remember_initial_snapshot(snapshot):
    bpy.app.driver_namespace[_SNAPSHOT_KEY] = snapshot


def restore_snapshot(snapshot, view_layer=None):
    if not snapshot:
        return False

    root_name = snapshot.get("root_name", "")
    root = bpy.data.objects.get(root_name) if root_name else None
    root_state = snapshot.get("root_state")
    if root is not None and root_state is not None:
        _restore_object_state(root, root_state)

    for object_name, state in snapshot.get("object_states", {}).items():
        obj = bpy.data.objects.get(object_name)
        if obj is not None:
            _restore_object_state(obj, state)

    armature_name = snapshot.get("armature_name", "")
    armature = bpy.data.objects.get(armature_name) if armature_name else None
    if armature is not None:
        for bone_name, matrix_basis in snapshot.get("pose_basis", {}).items():
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is not None:
                pose_bone.matrix_basis = matrix_basis.copy()

    for armature_name, bone_name, constraint_name, was_muted in snapshot.get("constraint_mutes", []):
        armature = bpy.data.objects.get(armature_name)
        if armature is None:
            continue
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        constraint = pose_bone.constraints.get(constraint_name)
        if constraint is not None:
            constraint.mute = was_muted

    _update_view_layer(view_layer)
    return True


def restore_last_initial_snapshot(view_layer=None):
    return restore_snapshot(bpy.app.driver_namespace.get(_SNAPSHOT_KEY), view_layer)


class PhysicsWorld:
    def __init__(self):
        self.model = None
        self.native = None
        self._view_layer = None
        self.bone_driver_rigid_indices = {}
        self._disconnected_armature = None
        self._disconnected_bone_names = set()
        self._muted_mmd_tools_constraints = []
        self._muted_action_fcurves = []
        self._last_bone_targets = {}
        self._initial_pose_basis = {}
        self._initial_rigid_matrices = {}
        self._initial_snapshot = None
        self._prewarm_steps = 0
        self._last_kinematic_matrices = {}
        self._kinematic_smoothing_enabled = True
        self._kinematic_smoothing_steps = 12
        self._kinematic_smoothing_move = 0.03
        self._kinematic_smoothing_angle = math.radians(8.0)
        self.apply_options = _default_apply_options()
        self._bone_target_entries = []
        self._physics_pose_bones = []
        self._last_written_bone_targets = {}
        self._last_object_targets = {}
        self._last_root_world = None
        self._kinematic_cache = None
        self._kinematic_cache_dirty = True
        self._kinematic_cache_safe = False
        self._dynamic_bone_index_cache = None
        self._drag_previous_dynamic_matrices = {}
        self._drag_current_dynamic_matrices = {}
        self._drag_dynamic_blended_indices = set()
        self._drag_resync_pending = False
        self._drag_resync_indices = set()
        self.performance = _new_performance()

    @property
    def root(self):
        # Exposed so that physics_sync._iter_world_roots() can locate the
        # model root (and from there the armature) for single-model
        # PhysicsWorld instances. Without this property the interaction-scope
        # selection plumbing returns no armatures, so user-selected bones
        # never make it into the scope and parent-chain pose-matrix changes
        # leak unrelated cloth/hair bones into the drag-compensation set.
        if self.model is None:
            return None
        return self.model.root

    def initialize(
        self,
        context,
        root,
        dll_path,
        gravity,
        solver_iterations=20,
        use_frame_offset=True,
        joint_stop_erp=-1.0,
        joint_stop_cfm=-1.0,
        locked_joint_stop_erp=0.2,
        locked_joint_stop_cfm=0.0002,
        prewarm_steps=0,
        kinematic_smoothing=True,
        kinematic_smoothing_steps=12,
        kinematic_smoothing_move=0.03,
        kinematic_smoothing_angle=8.0,
        startup_sync_steps=0,
        locked_joint_pullback=True,
        resting_body_stabilization=False,
        apply_options=None,
    ):
        self._view_layer = getattr(context, "view_layer", None)
        self.apply_options = _normalize_apply_options(apply_options)
        self._flush_depsgraph()
        self.model = pmx_data_reader.read_model(context, root)
        self._capture_initial_state()
        self._mute_mmd_tools_physics_constraints()
        self._disconnect_physics_bones(context)
        self._flush_depsgraph()
        self.model = pmx_data_reader.read_model(context, root)
        self.bone_driver_rigid_indices = self._build_bone_driver_rigid_indices()
        self._build_runtime_cache()
        # The substep kinematic cache is only provably identical when every
        # STATIC rigid resolves through its pose bone: the object-matrix
        # fallback reads rigid.obj.matrix_world, which our own apply stage
        # rewrites between substeps. With any fallback-path static present
        # the cache stays disabled and collects recompute as before.
        self._kinematic_cache_safe = all(
            rigid.mode != MODE_STATIC
            or (
                rigid.bone_name
                and rigid.bone_offset_matrix is not None
                and getattr(rigid, "_pmx_cached_pose_bone", None) is not None
            )
            for rigid in self.model.rigid_bodies
        )
        if self._kinematic_cache_safe:
            # A bone bound to both a STATIC rigid and a physics-driven
            # dynamic rigid gets its pose rewritten by the apply stage
            # between substeps; caching would then serve stale matrices.
            static_followed_bones = {
                rigid.bone_name
                for rigid in self.model.rigid_bodies
                if rigid.mode == MODE_STATIC and rigid.bone_name
            }
            self._kinematic_cache_safe = not (
                static_followed_bones & set(self.bone_driver_rigid_indices.keys())
            )
        self._kinematic_cache = None
        self._kinematic_cache_dirty = True
        self.performance = _new_performance()
        self.performance.update(
            {
                "body_count": len(self.model.rigid_bodies),
                "joint_count": len(self.model.joints),
                "pair_count": len(self.model.non_collision_pairs),
            }
        )
        self.native = BulletNative(dll_path)
        self.native.create_world()
        self.native.set_solver_iterations(solver_iterations)
        self.native.set_joint_quality(
            use_frame_offset,
            joint_stop_erp,
            joint_stop_cfm,
            locked_joint_stop_erp,
            locked_joint_stop_cfm,
        )
        self.native.set_stabilization(locked_joint_pullback, resting_body_stabilization)
        self.native.set_gravity(gravity)
        self._prewarm_steps = int(prewarm_steps)
        self._kinematic_smoothing_enabled = bool(kinematic_smoothing)
        self._kinematic_smoothing_steps = max(1, min(64, int(kinematic_smoothing_steps)))
        self._kinematic_smoothing_move = max(0.001, float(kinematic_smoothing_move))
        self._kinematic_smoothing_angle = math.radians(max(0.1, float(kinematic_smoothing_angle)))
        target_matrices = self._current_body_matrices(include_dynamic=True)
        startup_sync_steps = max(0, min(300, int(startup_sync_steps)))
        initial_matrices = self._rest_body_matrices(include_dynamic=True) if startup_sync_steps else target_matrices
        self.native.add_rigid_bodies(self.model, initial_matrices=initial_matrices)
        self.native.add_non_collision_pairs(self.model)
        self.native.add_joints(self.model)
        self.native.temporal_kinematic_init(initial_matrices)
        self._mute_physics_bone_action_curves()
        self._last_kinematic_matrices = self._copy_matrices(
            self._rest_body_matrices(include_dynamic=False) if startup_sync_steps else self._current_body_matrices(include_dynamic=False)
        )
        self._sync_to_start_pose(target_matrices, startup_sync_steps)
        self._prewarm(self._prewarm_steps)
        self._last_root_world = self.model.root.matrix_world.copy()
        self.flush_depsgraph()

    def destroy(self, restore_initial=False):
        if self.native is not None:
            self.native.destroy()
            self.native = None
        self._restore_physics_bone_action_curves()
        self._restore_mmd_tools_physics_constraints()
        self._restore_physics_bones()
        if restore_initial:
            self.restore_initial_state()
        self.model = None
        self._view_layer = None
        self.bone_driver_rigid_indices = {}
        self._last_bone_targets = {}
        self._initial_pose_basis = {}
        self._initial_rigid_matrices = {}
        self._initial_snapshot = None
        self._prewarm_steps = 0
        self._last_kinematic_matrices = {}
        self._drag_previous_dynamic_matrices = {}
        self._drag_current_dynamic_matrices = {}
        self._drag_dynamic_blended_indices = set()
        self._drag_resync_pending = False
        self._drag_resync_indices = set()
        self._muted_action_fcurves = []
        self._interaction_pose_scope = None
        self.apply_options = _default_apply_options()
        self._bone_target_entries = []
        self._physics_pose_bones = []
        self._last_written_bone_targets = {}
        self._last_object_targets = {}
        self._last_root_world = None
        self._kinematic_cache = None
        self._kinematic_cache_dirty = True
        self._kinematic_cache_safe = False
        self._dynamic_bone_index_cache = None
        self._interaction_pose_scope = None
        self.performance = _new_performance()

    def set_initial_snapshot(self, snapshot):
        if snapshot:
            self._initial_snapshot = snapshot
            remember_initial_snapshot(snapshot)

    def configure_apply_options(self, options):
        self.apply_options = _normalize_apply_options(options)

    def set_interaction_pose_scope(self, pose_bones=None):
        self._interaction_pose_scope = pose_bones
        if pose_bones is None:
            self.performance["interaction_static_scope_count"] = 0
            self.performance["interaction_dynamic_scope_count"] = 0
            self.performance["interaction_frozen_dynamic_count"] = 0
            self.performance["interaction_static_bodies"] = ""
            self.performance["interaction_dynamic_bodies"] = ""
            self.performance["interaction_written_bones"] = ""

    def reset(self):
        self.restore_initial_state()
        if self.native is None:
            return
        self.native.reset()
        self._last_bone_targets = {}
        self._last_written_bone_targets = {}
        self._last_object_targets = {}
        self._last_root_world = self.model.root.matrix_world.copy()
        self.native.temporal_kinematic_init(self._current_body_matrices(include_dynamic=True))
        self._last_kinematic_matrices = self._copy_matrices(self._current_body_matrices(include_dynamic=False))
        self._prewarm(self._prewarm_steps)
        self.flush_depsgraph()

    def reset_to_current_pose(self, prewarm_steps=0):
        if self.native is None:
            return
        self._restore_unanimated_physics_bone_basis()
        self.flush_depsgraph()
        self.native.reset()
        self._last_bone_targets = {}
        self._last_written_bone_targets = {}
        self._last_object_targets = {}
        self._last_root_world = self.model.root.matrix_world.copy()
        initial_matrices = self._current_body_matrices(include_dynamic=True)
        self.native.temporal_kinematic_init(initial_matrices)
        self._last_kinematic_matrices = self._copy_matrices(self._current_body_matrices(include_dynamic=False))
        self._prewarm(prewarm_steps)
        self.flush_depsgraph()

    def _restore_unanimated_physics_bone_basis(self):
        armature = self.model.armature if self.model is not None else None
        if armature is None:
            return

        animated_bones = self._animated_pose_bone_names(armature)
        for bone_name in self.dynamic_bone_names():
            if bone_name in animated_bones:
                continue
            pose_bone = armature.pose.bones.get(bone_name)
            matrix_basis = self._initial_pose_basis.get(bone_name)
            if pose_bone is not None and matrix_basis is not None:
                pose_bone.matrix_basis = matrix_basis.copy()

    @staticmethod
    def _animated_pose_bone_names(armature):
        animation_data = getattr(armature, "animation_data", None)
        if animation_data is None:
            return set()

        actions = []
        if animation_data.action is not None:
            actions.append(animation_data.action)
        for track in animation_data.nla_tracks:
            if track.mute:
                continue
            for strip in track.strips:
                if strip.action is not None:
                    actions.append(strip.action)
        if not actions:
            return set()

        bone_paths = {
            pose_bone.path_from_id() + ".": pose_bone.name
            for pose_bone in armature.pose.bones
        }
        animated_bones = set()
        for action in actions:
            for fcurve in action.fcurves:
                data_path = str(fcurve.data_path)
                for prefix, bone_name in bone_paths.items():
                    if data_path.startswith(prefix):
                        animated_bones.add(bone_name)
                        break
        return animated_bones

    def _prewarm(self, steps):
        steps = int(steps)
        if steps <= 0 or self.native is None:
            return
        kinematic_matrices = self._current_body_matrices(include_dynamic=False)
        for _ in range(steps):
            self.native.set_kinematic_transforms(kinematic_matrices)
            self.native.step(1.0 / 30.0, 1)
        self.native.prewarm(0, 1.0 / 30.0)
        body_matrices = self.native.get_body_transforms(len(self.model.rigid_bodies))
        self._apply_body_matrices(body_matrices)
        self._last_kinematic_matrices = self._copy_matrices(kinematic_matrices)

    def restore_initial_state(self):
        if self.model is None:
            return
        if restore_snapshot(self._initial_snapshot, self._view_layer):
            self._last_bone_targets = {}
            self._last_written_bone_targets = {}
            self._last_object_targets = {}
            return

        armature = self.model.armature
        if armature is not None:
            for bone_name, matrix_basis in self._initial_pose_basis.items():
                pose_bone = armature.pose.bones.get(bone_name)
                if pose_bone is not None:
                    pose_bone.matrix_basis = matrix_basis.copy()

        for object_name, matrix_world in self._initial_rigid_matrices.items():
            obj = bpy.data.objects.get(object_name)
            if obj is not None:
                obj.matrix_world = matrix_world.copy()

        self._last_bone_targets = {}
        self._last_written_bone_targets = {}
        self._last_object_targets = {}
        self.flush_depsgraph()

    def step(self, timestep, max_substeps, apply_results=True):
        start_time = time.perf_counter()
        if bool(self.apply_options.get("follow_root_motion", True)):
            if self._last_root_world is None and self.model is not None and self.model.root is not None:
                self._last_root_world = self.model.root.matrix_world.copy()
        else:
            self._preserve_dynamic_world_space_on_root_motion()
        collect_start = start_time
        kinematic_matrices = self._current_body_matrices(include_dynamic=False)
        self._prepare_drag_dynamic_compensation()
        collect_ms = (time.perf_counter() - collect_start) * 1000.0
        native_start = time.perf_counter()
        # Previously we collected every out-of-scope dynamic body and called
        # `freeze_body_transforms` on them after stepping, which pinned cloth
        # and hair in place during pose-mode dragging. That broke the MMD-like
        # expectation of "drag a bone while everything else keeps simulating".
        # Out-of-scope dynamics are *guaranteed* to be joint-disconnected from
        # the in-scope drag region (the scope expansion in
        # `_interaction_dynamic_indices_from_static_scope` walks every joint
        # neighbor), and their matching STATIC anchors are already pinned to
        # the previous-frame kinematic matrix in `_current_body_matrices` so
        # parent-chain pose-matrix bleed-through cannot pull them either. Let
        # them free-run.
        self._step_with_kinematic_smoothing(kinematic_matrices, timestep, max_substeps)
        native_ms = (time.perf_counter() - native_start) * 1000.0
        self._last_kinematic_matrices = self._copy_matrices(kinematic_matrices)
        readback_ms = 0.0
        apply_ms = 0.0
        if apply_results:
            readback_start = time.perf_counter()
            body_matrices = self.native.get_body_transforms(len(self.model.rigid_bodies))
            readback_ms = (time.perf_counter() - readback_start) * 1000.0
            apply_start = time.perf_counter()
            self._apply_body_matrices(body_matrices)
            apply_ms = (time.perf_counter() - apply_start) * 1000.0
        if self.model is not None and self.model.root is not None:
            self._last_root_world = self.model.root.matrix_world.copy()
        self._record_step_time(
            (time.perf_counter() - start_time) * 1000.0,
            {
                "collect_ms": collect_ms,
                "native_ms": native_ms,
                "readback_ms": readback_ms,
                "apply_ms": apply_ms,
            },
        )

    def sync_kinematic_only(self):
        if self.native is None or self.model is None:
            return 0
        kinematic_matrices = self._current_body_matrices(include_dynamic=False)
        self.native.set_kinematic_transforms(kinematic_matrices)
        self._last_kinematic_matrices = self._copy_matrices(kinematic_matrices)
        return len(kinematic_matrices)

    def interaction_snap_dynamic_bones(self, clear_velocity=False, pose_bones=None):
        if self.native is None or self.model is None:
            return 0

        affected_indices = self._interaction_affected_dynamic_bone_indices(pose_bones)
        if affected_indices is not None and not affected_indices:
            return 0

        transforms = {}
        for rigid in self.model.rigid_bodies:
            if rigid.mode != MODE_DYNAMIC_BONE:
                continue
            if affected_indices is not None and rigid.index not in affected_indices:
                continue
            if not rigid.bone_name or rigid.bone_offset_matrix is None:
                continue
            transforms[rigid.index] = self._current_body_matrix(rigid)

        if not transforms:
            return 0
        if clear_velocity:
            self.native.freeze_body_transforms(transforms)
        else:
            self.native.temporal_kinematic_init(transforms)
        return len(transforms)

    def _interaction_affected_dynamic_bone_indices(self, pose_bones):
        if pose_bones is None:
            return None
        if self.model is None or self.model.armature is None:
            return set()

        dynamic_indices = self._interaction_dynamic_indices_from_static_scope(pose_bones)
        return {
            rigid.index
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_DYNAMIC_BONE and rigid.index in dynamic_indices
        }

    def _interaction_affected_dynamic_indices(self):
        pose_bones = getattr(self, "_interaction_pose_scope", None)
        if pose_bones is None:
            self.performance["interaction_dynamic_scope_count"] = 0
            return None
        indices = self._interaction_dynamic_indices_from_static_scope(pose_bones)
        self.performance["interaction_dynamic_scope_count"] = len(indices)
        self.performance["interaction_dynamic_bodies"] = self._format_debug_names(
            self._rigid_names_for_indices(indices),
            limit=8,
        )
        return indices

    def _interaction_dynamic_indices_from_static_scope(self, pose_bones):
        static_indices = self._interaction_static_indices_for_pose_scope(pose_bones)
        if not static_indices:
            return set()

        rigid_by_index = {rigid.index: rigid for rigid in self.model.rigid_bodies}
        dynamic_indices = set()
        seeds = set()

        for joint in self.model.joints:
            a = rigid_by_index.get(joint.rigid_a_index)
            b = rigid_by_index.get(joint.rigid_b_index)
            if a is None or b is None:
                continue
            if a.index in static_indices and b.mode in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                seeds.add(b.index)
            elif b.index in static_indices and a.mode in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                seeds.add(a.index)

        pending = list(seeds)
        while pending:
            index = pending.pop()
            if index in dynamic_indices:
                continue
            rigid = rigid_by_index.get(index)
            if rigid is None or rigid.mode not in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                continue
            dynamic_indices.add(index)
            for neighbor in self._dynamic_joint_neighbors(index, rigid_by_index):
                if neighbor not in dynamic_indices:
                    pending.append(neighbor)
        return dynamic_indices

    def _interaction_static_indices_for_pose_scope(self, pose_bones):
        input_bone_names = self._interaction_input_bone_names(pose_bones)
        if not input_bone_names:
            return set()
        return {
            rigid.index
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_STATIC and rigid.bone_name in input_bone_names
        }

    def _dynamic_joint_neighbors(self, rigid_index, rigid_by_index):
        for joint in self.model.joints:
            neighbor_index = None
            if joint.rigid_a_index == rigid_index:
                neighbor_index = joint.rigid_b_index
            elif joint.rigid_b_index == rigid_index:
                neighbor_index = joint.rigid_a_index
            if neighbor_index is None:
                continue
            neighbor = rigid_by_index.get(neighbor_index)
            if neighbor is not None and neighbor.mode in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                yield neighbor.index

    def _interaction_preserved_dynamic_transforms(self):
        if self.native is None or self.model is None:
            return {}
        dynamic_scope = self._interaction_affected_dynamic_indices()
        if dynamic_scope is None:
            self.performance["interaction_frozen_dynamic_count"] = 0
            return {}

        body_matrices = self.native.get_body_transforms(len(self.model.rigid_bodies))
        preserved = {}
        for rigid in self.model.rigid_bodies:
            if rigid.mode not in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                continue
            if rigid.index in dynamic_scope:
                continue
            matrix = body_matrices.get(rigid.index)
            if matrix is not None:
                preserved[rigid.index] = matrix
        self.performance["interaction_frozen_dynamic_count"] = len(preserved)
        return preserved

    def _interaction_affected_bone_names(self, pose_bones):
        if self.model is None or self.model.armature is None or not pose_bones:
            return set()

        armature = self.model.armature
        changed_bone_names = {
            bone_name
            for scoped_armature, bone_name in pose_bones
            if scoped_armature == armature.name
        }
        if not changed_bone_names:
            return set()

        affected = set(changed_bone_names)
        pending = [
            armature.pose.bones.get(bone_name)
            for bone_name in changed_bone_names
        ]
        pending = [pose_bone for pose_bone in pending if pose_bone is not None]
        while pending:
            pose_bone = pending.pop()
            for child in pose_bone.children:
                if child.name in affected:
                    continue
                affected.add(child.name)
                pending.append(child)
        return affected

    def _interaction_input_bone_names(self, pose_bones):
        if self.model is None or self.model.armature is None or not pose_bones:
            return set()

        armature_name = self.model.armature.name
        return {
            bone_name
            for scoped_armature, bone_name in pose_bones
            if scoped_armature == armature_name and bone_name
        }

    def _preserve_dynamic_world_space_on_root_motion(self):
        if self.native is None or self.model is None or self.model.root is None:
            return

        previous_root = self._last_root_world
        current_root = self.model.root.matrix_world.copy()
        if previous_root is None:
            self._last_root_world = current_root
            return

        move, angle = self._matrix_delta(previous_root, current_root)
        if move <= 1.0e-6 and angle <= 1.0e-5:
            return

        root_inverse = current_root.inverted_safe()
        body_matrices = self.native.get_body_transforms(len(self.model.rigid_bodies))
        adjusted = {}
        for rigid in self.model.rigid_bodies:
            if rigid.mode not in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                continue
            matrix = body_matrices.get(rigid.index)
            if matrix is None:
                continue
            adjusted[rigid.index] = root_inverse @ previous_root @ matrix
        if adjusted:
            self.native.temporal_kinematic_init(adjusted)

    def _record_step_time(self, elapsed_ms, stages=None):
        count = int(self.performance.get("step_count", 0)) + 1
        previous_avg = float(self.performance.get("avg_step_ms", 0.0))
        self.performance["step_count"] = count
        self.performance["last_step_ms"] = float(elapsed_ms)
        self.performance["avg_step_ms"] = previous_avg + (float(elapsed_ms) - previous_avg) / count
        self.performance["max_step_ms"] = max(float(self.performance.get("max_step_ms", 0.0)), float(elapsed_ms))
        if stages:
            for key, value in stages.items():
                value = float(value)
                self.performance[f"last_{key}"] = value
                avg_key = f"avg_{key}"
                max_key = f"max_{key}"
                previous_stage_avg = float(self.performance.get(avg_key, 0.0))
                self.performance[avg_key] = previous_stage_avg + (value - previous_stage_avg) / count
                self.performance[max_key] = max(float(self.performance.get(max_key, 0.0)), value)

    def record_tick_time(self, elapsed_ms, steps):
        count = int(self.performance.get("tick_count", 0)) + 1
        previous_avg = float(self.performance.get("avg_tick_ms", 0.0))
        value = float(elapsed_ms)
        self.performance["tick_count"] = count
        self.performance["last_tick_ms"] = value
        self.performance["avg_tick_ms"] = previous_avg + (value - previous_avg) / count
        self.performance["max_tick_ms"] = max(float(self.performance.get("max_tick_ms", 0.0)), value)
        self.performance["last_tick_steps"] = int(steps)

    def record_flush_time(self, elapsed_ms):
        count = int(self.performance.get("flush_count", 0)) + 1
        previous_avg = float(self.performance.get("avg_flush_ms", 0.0))
        value = float(elapsed_ms)
        self.performance["flush_count"] = count
        self.performance["last_flush_ms"] = value
        self.performance["avg_flush_ms"] = previous_avg + (value - previous_avg) / count
        self.performance["max_flush_ms"] = max(float(self.performance.get("max_flush_ms", 0.0)), value)

    def _step_with_kinematic_smoothing(self, kinematic_matrices, timestep, max_substeps):
        if (
            not self._kinematic_smoothing_enabled
            or self._kinematic_smoothing_steps <= 1
            or not self._last_kinematic_matrices
        ):
            self.performance["last_smoothing_segments"] = 1
            self.native.set_kinematic_transforms(kinematic_matrices)
            self.native.step(timestep, max_substeps)
            self._apply_drag_dynamic_resync()
            return

        segments = self._kinematic_segment_count(kinematic_matrices)
        self.performance["last_smoothing_segments"] = int(segments)
        self.performance["max_smoothing_segments"] = max(
            int(self.performance.get("max_smoothing_segments", 1)),
            int(segments),
        )
        if segments <= 1:
            self.native.set_kinematic_transforms(kinematic_matrices)
            self.native.step(timestep, max_substeps)
            self._apply_drag_dynamic_resync()
            return

        sub_timestep = timestep / segments
        for segment in range(1, segments + 1):
            factor = segment / segments
            blended = self._interpolate_kinematic_matrices(kinematic_matrices, factor, include_static_fallback=True)
            self.native.set_kinematic_transforms(blended)
            self.native.step(sub_timestep, 1)
        self._apply_drag_dynamic_resync()

    def _kinematic_segment_count(self, kinematic_matrices):
        segments = 1
        for index, matrix in kinematic_matrices.items():
            previous = self._last_kinematic_matrices.get(index)
            if previous is None:
                continue
            move, angle = self._matrix_delta(previous, matrix)
            if move > self._kinematic_smoothing_move:
                segments = max(segments, math.ceil(move / self._kinematic_smoothing_move))
            if angle > self._kinematic_smoothing_angle:
                segments = max(segments, math.ceil(angle / self._kinematic_smoothing_angle))
        if bool(self.apply_options.get("drag_compensation", True)):
            root_segments = self._root_motion_segment_count()
            if root_segments > 1:
                segments = max(segments, root_segments)
            dynamic_segments = self._dynamic_bone_segment_count()
            if dynamic_segments > 1:
                segments = max(segments, dynamic_segments)
            limit = max(int(self._kinematic_smoothing_steps), int(self.apply_options.get("drag_max_segments", 32)))
        else:
            limit = int(self._kinematic_smoothing_steps)
        return max(1, min(max(1, limit), segments))

    def _root_motion_segment_count(self):
        if self.model is None or self.model.root is None or self._last_root_world is None:
            return 1
        move, angle = self._matrix_delta(self._last_root_world, self.model.root.matrix_world)
        segments = 1
        if move > self._kinematic_smoothing_move:
            segments = max(segments, math.ceil(move / self._kinematic_smoothing_move))
        if angle > self._kinematic_smoothing_angle:
            segments = max(segments, math.ceil(angle / self._kinematic_smoothing_angle))
        return segments

    def _dynamic_bone_segment_count(self):
        if not bool(self.apply_options.get("drag_compensate_dynamic_bone", True)):
            return 1
        segments = 1
        self._drag_dynamic_blended_indices = set()
        self._drag_resync_indices = set()
        for index, current in self._drag_current_dynamic_matrices.items():
            previous = self._drag_previous_dynamic_matrices.get(index)
            if previous is None:
                continue
            move, angle = self._matrix_delta(previous, current)
            if move > self._kinematic_smoothing_move:
                segments = max(segments, math.ceil(move / self._kinematic_smoothing_move))
            if angle > self._kinematic_smoothing_angle:
                segments = max(segments, math.ceil(angle / self._kinematic_smoothing_angle))
            if self._should_extreme_drag_resync(move):
                self._drag_resync_indices.add(index)
            self._drag_dynamic_blended_indices.add(index)
        self._drag_resync_pending = bool(self._drag_resync_indices)
        return segments

    def _interpolate_kinematic_matrices(self, kinematic_matrices, factor, include_static_fallback=False):
        blended = {}
        for index, matrix in kinematic_matrices.items():
            previous = self._last_kinematic_matrices.get(index)
            if previous is None:
                if include_static_fallback:
                    previous = self._fallback_previous_kinematic_matrix(matrix)
                else:
                    previous = None
            if previous is None:
                blended[index] = matrix
            else:
                blended[index] = self._interpolate_matrix(previous, matrix, factor)
        return blended

    def _fallback_previous_kinematic_matrix(self, matrix):
        if not bool(self.apply_options.get("drag_compensate_static", True)):
            return None
        if self.model is None or self.model.root is None or self._last_root_world is None:
            return None
        current_root = self.model.root.matrix_world
        move, angle = self._matrix_delta(self._last_root_world, current_root)
        if move <= 1.0e-6 and angle <= 1.0e-5:
            return None
        return current_root.inverted_safe() @ self._last_root_world @ matrix

    def _prepare_drag_dynamic_compensation(self):
        self._drag_previous_dynamic_matrices = {}
        self._drag_current_dynamic_matrices = {}
        self._drag_dynamic_blended_indices = set()
        self._drag_resync_pending = False
        self._drag_resync_indices = set()
        if (
            not bool(self.apply_options.get("drag_compensation", True))
            or self.native is None
            or self.model is None
            or not bool(self.apply_options.get("drag_compensate_dynamic_bone", True))
        ):
            return

        dynamic_scope = self._interaction_affected_dynamic_indices()
        if dynamic_scope is not None and not dynamic_scope:
            return

        body_matrices = self.native.get_body_transforms(
            len(self.model.rigid_bodies),
            wanted_indices=self._dynamic_bone_indices(),
        )
        # Hoisted once per loop like in `_collect_body_matrices`: one root
        # inversion instead of one per dynamic-bone rigid.
        root_inverse = None
        armature_world = None
        if self.model.root is not None:
            root_inverse = self.model.root.matrix_world.inverted_safe()
        if self.model.armature is not None:
            armature_world = self.model.armature.matrix_world
        for rigid in self.model.rigid_bodies:
            if rigid.mode != MODE_DYNAMIC_BONE:
                continue
            if dynamic_scope is not None and rigid.index not in dynamic_scope:
                continue
            previous = body_matrices.get(rigid.index)
            if previous is None:
                continue
            current = self._current_body_matrix(rigid, root_inverse, armature_world)
            self._drag_previous_dynamic_matrices[rigid.index] = previous
            self._drag_current_dynamic_matrices[rigid.index] = current

    def _dynamic_bone_indices(self):
        cached = getattr(self, "_dynamic_bone_index_cache", None)
        if cached is None:
            cached = {
                rigid.index
                for rigid in (self.model.rigid_bodies if self.model else ())
                if rigid.mode == MODE_DYNAMIC_BONE
            }
            self._dynamic_bone_index_cache = cached
        return cached

    def _apply_drag_dynamic_resync(self):
        if self.native is None or not self._drag_resync_pending:
            return

        transforms = {
            index: self._drag_current_dynamic_matrices[index]
            for index in self._drag_resync_indices
            if index in self._drag_current_dynamic_matrices
        }
        if transforms:
            if bool(self.apply_options.get("drag_resync_clear_velocity", False)):
                self.native.freeze_body_transforms(transforms)
            else:
                self.native.temporal_kinematic_init(transforms)
        self._drag_resync_pending = False

    def _should_extreme_drag_resync(self, move):
        return (
            bool(self.apply_options.get("drag_resync", True))
            and move >= float(self.apply_options.get("drag_resync_threshold", 0.5))
        )

    @staticmethod
    def _copy_matrices(matrices):
        return {index: matrix.copy() for index, matrix in matrices.items()}

    @staticmethod
    def _matrix_delta(matrix_a, matrix_b):
        loc_a, rot_a, _scale_a = matrix_a.decompose()
        loc_b, rot_b, _scale_b = matrix_b.decompose()
        return (loc_b - loc_a).length, rot_a.rotation_difference(rot_b).angle

    @staticmethod
    def _interpolate_matrix(matrix_a, matrix_b, factor):
        loc_a, rot_a, scale_a = matrix_a.decompose()
        loc_b, rot_b, scale_b = matrix_b.decompose()
        loc = loc_a.lerp(loc_b, factor)
        rot = rot_a.slerp(rot_b, factor)
        scale = scale_a.lerp(scale_b, factor)
        return Matrix.LocRotScale(loc, rot, scale)

    def dynamic_bone_names(self):
        names = []
        for rigid in self.model.rigid_bodies:
            if rigid.mode in {MODE_DYNAMIC, MODE_DYNAMIC_BONE} and rigid.bone_name and rigid.bone_name not in names:
                names.append(rigid.bone_name)
        return names

    def _mute_physics_bone_action_curves(self):
        armature = self.model.armature if self.model is not None else None
        if armature is None:
            return

        dynamic_bones = {
            rigid.bone_name
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_DYNAMIC and rigid.bone_name
        }
        dynamic_bone_merge_bones = {
            rigid.bone_name
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_DYNAMIC_BONE and rigid.bone_name
        }
        if not dynamic_bones and not dynamic_bone_merge_bones:
            return

        animation_data = getattr(armature, "animation_data", None)
        if animation_data is None:
            return

        actions = []
        if animation_data.action is not None:
            actions.append(animation_data.action)
        for track in animation_data.nla_tracks:
            if track.mute:
                continue
            for strip in track.strips:
                if strip.action is not None:
                    actions.append(strip.action)

        seen_actions = set()
        for action in actions:
            if action is None or action.name in seen_actions:
                continue
            seen_actions.add(action.name)
            for fcurve in action.fcurves:
                muted_paths = self._physics_bone_muted_data_paths(
                    str(fcurve.data_path),
                    dynamic_bones,
                    dynamic_bone_merge_bones,
                )
                if muted_paths and not bool(fcurve.mute):
                    self._muted_action_fcurves.append((fcurve, False))
                    fcurve.mute = True

    @staticmethod
    def _physics_bone_muted_data_paths(data_path, dynamic_bones, dynamic_bone_merge_bones):
        for bone_name in dynamic_bones:
            prefix = f'pose.bones["{bone_name}"].'
            if data_path.startswith(prefix) and data_path[len(prefix):] in {
                "location",
                "rotation_euler",
                "rotation_quaternion",
                "rotation_axis_angle",
                "scale",
            }:
                return True

        for bone_name in dynamic_bone_merge_bones:
            prefix = f'pose.bones["{bone_name}"].'
            if data_path.startswith(prefix) and data_path[len(prefix):] in {
                "rotation_euler",
                "rotation_quaternion",
                "rotation_axis_angle",
                "scale",
            }:
                return True
        return False

    def _restore_physics_bone_action_curves(self):
        muted = self._muted_action_fcurves
        self._muted_action_fcurves = []
        for fcurve, was_muted in muted:
            try:
                fcurve.mute = was_muted
            except ReferenceError:
                pass

    def _build_bone_driver_rigid_indices(self):
        drivers = {}
        for rigid in self.model.rigid_bodies:
            if rigid.mode not in {MODE_DYNAMIC, MODE_DYNAMIC_BONE} or not rigid.bone_name:
                continue
            current = drivers.get(rigid.bone_name)
            if current is None or rigid.mass > current.mass:
                drivers[rigid.bone_name] = rigid
        return {bone_name: rigid.index for bone_name, rigid in drivers.items()}

    def _capture_initial_state(self):
        self._initial_pose_basis = {}
        self._initial_rigid_matrices = {}
        self._initial_snapshot = capture_initial_snapshot(self.model)
        remember_initial_snapshot(self._initial_snapshot)

        armature = self.model.armature if self.model is not None else None
        if armature is not None:
            self._initial_pose_basis = {
                pose_bone.name: pose_bone.matrix_basis.copy()
                for pose_bone in armature.pose.bones
            }

        if self.model is not None:
            self._initial_rigid_matrices = {
                rigid.obj.name: rigid.obj.matrix_world.copy()
                for rigid in self.model.rigid_bodies
                if rigid.obj is not None
            }

    def flush_depsgraph(self):
        self._kinematic_cache_dirty = True
        view_layer = self._view_layer
        if view_layer is None:
            return
        try:
            view_layer.update()
        except ReferenceError:
            self._view_layer = None
        except RuntimeError:
            pass

    def _flush_depsgraph(self):
        self.flush_depsgraph()

    def _current_body_matrices(self, include_dynamic):
        if not include_dynamic and self._kinematic_cache_safe:
            # Between substeps nothing a static rigid follows can change:
            # pose matrices are only refreshed by flush_depsgraph (frame
            # moves, user transforms) and our apply stage never writes
            # static-bound bones. Reuse the cached collect instead of
            # re-evaluating every pose matrix (the dominant collect cost).
            if self._kinematic_cache is not None and not self._kinematic_cache_dirty:
                return dict(self._kinematic_cache)
            collected = self._collect_body_matrices(include_dynamic)
            self._kinematic_cache = dict(collected)
            self._kinematic_cache_dirty = False
            return collected
        return self._collect_body_matrices(include_dynamic)

    def _collect_body_matrices(self, include_dynamic):
        matrices = {}
        if not include_dynamic:
            # Touch the static-scope helper so debug metrics
            # (`interaction_static_scope_count`, `interaction_static_bodies`)
            # still get published even though we no longer use the result to
            # gate kinematic following.
            self._interaction_affected_static_indices()
        # Hoisted once per call: inverting the root matrix per rigid body
        # dominated the collect stage on dense PMX models (300+ bodies).
        root_inverse = None
        armature_world = None
        armature = self.model.armature
        if self.model.root is not None:
            root_inverse = self.model.root.matrix_world.inverted_safe()
        if armature is not None:
            armature_world = armature.matrix_world
        # Every kinematic STATIC body must follow its current bone matrix on
        # every frame, identical to MMD's behavior. Earlier versions pinned
        # out-of-scope STATIC bodies to the previous frame's kinematic matrix
        # in an attempt to mask parent-chain pose-matrix bleed, but that broke
        # the bone hierarchy: dragging the upper-arm bone left the forearm /
        # hand / finger STATIC anchors stuck in their pre-drag positions while
        # the underlying bones rotated through them, which caused arm dynamics
        # to explode at the joints and made self-collision visually disappear
        # because the static collision shells were lagging the visible mesh.
        # The interaction scope must only constrain the drag-protection logic
        # (`_prepare_drag_dynamic_compensation`), never the kinematic followers
        # themselves.
        for rigid in self.model.rigid_bodies:
            if rigid.mode == MODE_STATIC or include_dynamic:
                matrices[rigid.index] = self._current_body_matrix(
                    rigid, root_inverse, armature_world
                )
        return matrices

    def _rest_body_matrices(self, include_dynamic):
        matrices = {}
        for rigid in self.model.rigid_bodies:
            if rigid.mode == MODE_STATIC or include_dynamic:
                matrices[rigid.index] = self._rest_body_matrix(rigid)
        return matrices

    def _current_body_matrix(self, rigid, root_inverse=None, armature_world=None):
        if rigid.bone_name and rigid.bone_offset_matrix is not None:
            pose_bone = getattr(rigid, "_pmx_cached_pose_bone", None)
            if pose_bone is None and armature_world is not None:
                pose_bone = self.model.armature.pose.bones.get(rigid.bone_name)
            if pose_bone is not None:
                if root_inverse is None:
                    root_inverse = self.model.root.matrix_world.inverted_safe()
                if armature_world is None:
                    armature_world = self.model.armature.matrix_world
                bone_matrix = root_inverse @ armature_world @ pose_bone.matrix
                return bone_matrix @ rigid.bone_offset_matrix
        return self.model.root.matrix_world.inverted_safe() @ rigid.obj.matrix_world

    def _interaction_affected_static_indices(self):
        pose_bones = getattr(self, "_interaction_pose_scope", None)
        if pose_bones is None:
            self.performance["interaction_static_scope_count"] = 0
            return None
        indices = self._interaction_static_indices_for_pose_scope(pose_bones)
        if not indices:
            self.performance["interaction_static_scope_count"] = 0
            self.performance["interaction_static_bodies"] = ""
            return set()
        self.performance["interaction_static_scope_count"] = len(indices)
        self.performance["interaction_static_bodies"] = self._format_debug_names(
            self._rigid_names_for_indices(indices),
            limit=8,
        )
        return indices

    def _rigid_names_for_indices(self, indices):
        if self.model is None:
            return []
        index_set = set(indices or [])
        names = []
        for rigid in self.model.rigid_bodies:
            if rigid.index in index_set:
                names.append(rigid.name or rigid.obj.name or str(rigid.index))
        return names

    def _rest_body_matrix(self, rigid):
        if rigid.bone_name and rigid.bone_offset_matrix is not None:
            bone_matrix = pmx_data_reader.bone_rest_model_matrix(self.model, rigid.bone_name)
            if bone_matrix is not None:
                return bone_matrix @ rigid.bone_offset_matrix
        return rigid.local_matrix.copy()

    def _sync_to_start_pose(self, target_matrices, steps):
        if steps <= 0 or self.native is None:
            return

        kinematic_targets = {
            rigid.index: target_matrices[rigid.index]
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_STATIC and rigid.index in target_matrices
        }
        if not kinematic_targets:
            return

        start_matrices = self._copy_matrices(self._last_kinematic_matrices)
        for step in range(1, steps + 1):
            factor = step / steps
            blended = {}
            for index, matrix in kinematic_targets.items():
                previous = start_matrices.get(index)
                blended[index] = matrix if previous is None else self._interpolate_matrix(previous, matrix, factor)
            self.native.set_kinematic_transforms(blended)
            self.native.step(1.0 / 30.0, 1)

        self.native.prewarm(0, 1.0 / 30.0)
        body_matrices = self.native.get_body_transforms(len(self.model.rigid_bodies))
        self._apply_body_matrices(body_matrices)
        self._last_kinematic_matrices = self._copy_matrices(kinematic_targets)

    def _apply_body_matrices(self, body_matrices):
        root_world = self.model.root.matrix_world
        armature = self.model.armature
        armature_inverse = armature.matrix_world.inverted_safe() if armature is not None else None
        bone_targets = {}
        object_writes = 0
        dynamic_scope = self._interaction_affected_dynamic_indices()

        update_objects = bool(self.apply_options.get("update_rigid_objects", True))
        skip_objects = (
            self.apply_options.get("write_location_threshold", 0.0) > 0.0
            or self.apply_options.get("write_rotation_threshold", 0.0) > 0.0
        )

        for rigid in self.model.rigid_bodies:
            matrix = body_matrices.get(rigid.index)
            if matrix is None:
                continue
            if update_objects:
                object_matrix = root_world @ matrix
                if not skip_objects or self._should_write_object_target(rigid.index, object_matrix):
                    rigid.obj.matrix_world = object_matrix
                    object_writes += 1

            if rigid.mode not in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}:
                continue
            # Out-of-scope dynamic bodies are now allowed to free-run during
            # pose-mode interactions, so we still need to write their pose-bone
            # matrices back; otherwise the mesh would lag behind the physics
            # bodies. The scope still gates `_prepare_drag_dynamic_compensation`
            # and `_current_body_matrices`, which is enough to keep cloth/hair
            # decoupled from the dragged region.
            _ = dynamic_scope  # kept for performance metrics only
            if armature is None or armature_inverse is None or not rigid.bone_name or rigid.bone_offset_matrix is None:
                continue

            pose_bone = getattr(rigid, "_pmx_cached_pose_bone", None)
            if pose_bone is None:
                continue
            if self.bone_driver_rigid_indices.get(rigid.bone_name) != rigid.index:
                continue

            bone_matrix_model = matrix @ rigid.bone_offset_matrix.inverted_safe()
            bone_matrix_armature = armature_inverse @ root_world @ bone_matrix_model
            bone_targets[rigid.bone_name] = (pose_bone, rigid.mode, bone_matrix_armature)

        if armature is None:
            self.performance["last_bone_writes"] = 0
            self.performance["last_object_writes"] = object_writes
            return

        ordered_items = self._ordered_bone_targets(bone_targets)
        source_bones = self._physics_pose_bones if self._physics_pose_bones else [item[1][0] for item in ordered_items]
        original_basis_matrices = {
            bone.name: bone.matrix_basis.copy()
            for bone in source_bones
            if bone.name in bone_targets
        }
        applied_matrices = {}
        bone_writes = 0
        written_bone_names = []
        for bone_name, (pose_bone, mode, bone_matrix_armature) in ordered_items:
            if mode == MODE_DYNAMIC:
                target_matrix = bone_matrix_armature
            else:
                current_matrix = self._effective_pose_bone_matrix(
                    pose_bone,
                    applied_matrices,
                    original_basis_matrices,
                )
                current_loc, _current_rot, current_scale = current_matrix.decompose()
                _target_loc, target_rot, _target_scale = bone_matrix_armature.decompose()
                target_matrix = Matrix.LocRotScale(current_loc, target_rot, current_scale)
            target_matrix = self._stable_bone_target(bone_name, target_matrix)
            if self._skip_realtime_bone_write(bone_name, target_matrix):
                applied_matrices[bone_name] = self._last_written_bone_targets.get(bone_name, target_matrix)
                continue
            self._set_pose_bone_matrix_basis(
                pose_bone,
                target_matrix,
                applied_matrices,
                original_basis_matrices,
            )
            self._last_written_bone_targets[bone_name] = target_matrix.copy()
            bone_writes += 1
            written_bone_names.append(bone_name)
            applied_matrices[bone_name] = target_matrix
        self.performance["last_bone_writes"] = bone_writes
        self.performance["last_object_writes"] = object_writes
        self.performance["interaction_written_bones"] = self._format_debug_names(written_bone_names)

    @staticmethod
    def _format_debug_names(names, limit=10):
        names = [str(name) for name in names if name]
        if not names:
            return ""
        shown = names[:limit]
        suffix = f" +{len(names) - limit}" if len(names) > limit else ""
        return ", ".join(shown) + suffix

    def _build_runtime_cache(self):
        armature = self.model.armature if self.model is not None else None
        self._bone_target_entries = []
        self._physics_pose_bones = []
        if armature is None:
            return

        pose_bone_by_name = armature.pose.bones
        pose_bone_names = set()
        for rigid in self.model.rigid_bodies:
            pose_bone = None
            if rigid.bone_name:
                pose_bone = pose_bone_by_name.get(rigid.bone_name)
                if pose_bone is not None:
                    rigid._pmx_cached_pose_bone = pose_bone
                    pose_bone_names.add(pose_bone.name)
            if (
                rigid.mode in {MODE_DYNAMIC, MODE_DYNAMIC_BONE}
                and rigid.bone_name
                and pose_bone is not None
                and rigid.bone_offset_matrix is not None
                and self.bone_driver_rigid_indices.get(rigid.bone_name) == rigid.index
            ):
                self._bone_target_entries.append((self._pose_bone_depth(pose_bone), rigid.bone_name))

        for pose_bone in armature.pose.bones:
            if pose_bone.name in pose_bone_names:
                self._physics_pose_bones.append(pose_bone)

    def _ordered_bone_targets(self, bone_targets):
        if not self._bone_target_entries:
            return sorted(bone_targets.items(), key=lambda item: (self._pose_bone_depth(item[1][0]), item[0]))
        ordered = []
        seen = set()
        for _depth, bone_name in self._bone_target_entries:
            target = bone_targets.get(bone_name)
            if target is not None:
                ordered.append((bone_name, target))
                seen.add(bone_name)
        if len(seen) != len(bone_targets):
            for item in sorted(bone_targets.items(), key=lambda item: (self._pose_bone_depth(item[1][0]), item[0])):
                if item[0] not in seen:
                    ordered.append(item)
        return ordered

    def _skip_realtime_bone_write(self, bone_name, target_matrix):
        if not bool(self.apply_options.get("skip_unchanged_bones", False)):
            return False
        previous = self._last_written_bone_targets.get(bone_name)
        if previous is None:
            return False
        loc_threshold = float(self.apply_options.get("write_location_threshold", 0.0))
        rot_threshold = float(self.apply_options.get("write_rotation_threshold", 0.0))
        return self._matrix_within_threshold(previous, target_matrix, loc_threshold, rot_threshold)

    def _should_write_object_target(self, rigid_index, target_matrix):
        previous = self._last_object_targets.get(rigid_index)
        self._last_object_targets[rigid_index] = target_matrix.copy()
        if previous is None:
            return True
        loc_threshold = float(self.apply_options.get("write_location_threshold", 0.0))
        rot_threshold = float(self.apply_options.get("write_rotation_threshold", 0.0))
        return not self._matrix_within_threshold(previous, target_matrix, loc_threshold, rot_threshold)

    @staticmethod
    def _pose_bone_depth(pose_bone):
        depth = 0
        parent = pose_bone.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        return depth

    @staticmethod
    def _set_pose_bone_matrix_basis(pose_bone, target_matrix, applied_matrices, original_basis_matrices):
        rest_matrix = pose_bone.bone.matrix_local
        parent = pose_bone.parent
        if parent is None:
            pose_bone.matrix_basis = rest_matrix.inverted_safe() @ target_matrix
            return

        parent_matrix = PhysicsWorld._effective_pose_bone_matrix(
            parent,
            applied_matrices,
            original_basis_matrices,
        )
        parent_rest_matrix = parent.bone.matrix_local
        pose_bone.matrix_basis = (
            rest_matrix.inverted_safe()
            @ parent_rest_matrix
            @ parent_matrix.inverted_safe()
            @ target_matrix
        )

    @staticmethod
    def _effective_pose_bone_matrix(pose_bone, applied_matrices, original_basis_matrices):
        matrix = applied_matrices.get(pose_bone.name)
        if matrix is not None:
            return matrix

        rest_matrix = pose_bone.bone.matrix_local
        basis_matrix = original_basis_matrices.get(pose_bone.name, pose_bone.matrix_basis)
        parent = pose_bone.parent
        if parent is None:
            return rest_matrix @ basis_matrix

        parent_matrix = PhysicsWorld._effective_pose_bone_matrix(
            parent,
            applied_matrices,
            original_basis_matrices,
        )
        parent_rest_matrix = parent.bone.matrix_local
        return parent_matrix @ parent_rest_matrix.inverted_safe() @ rest_matrix @ basis_matrix

    def _stable_bone_target(self, bone_name, target_matrix):
        previous = self._last_bone_targets.get(bone_name)
        if previous is None:
            self._last_bone_targets[bone_name] = target_matrix.copy()
            return target_matrix

        if self._matrix_nearly_equal(previous, target_matrix):
            return previous

        self._last_bone_targets[bone_name] = target_matrix.copy()
        return target_matrix

    @staticmethod
    def _matrix_nearly_equal(matrix_a, matrix_b):
        loc_a, rot_a, _scale_a = matrix_a.decompose()
        loc_b, rot_b, _scale_b = matrix_b.decompose()
        if (loc_a - loc_b).length > 1.5e-4:
            return False
        return 1.0 - abs(rot_a.dot(rot_b)) < 1.0e-6

    @staticmethod
    def _matrix_within_threshold(matrix_a, matrix_b, loc_threshold, rot_threshold):
        loc_a, rot_a, _scale_a = matrix_a.decompose()
        loc_b, rot_b, _scale_b = matrix_b.decompose()
        if (loc_a - loc_b).length > loc_threshold:
            return False
        return rot_a.rotation_difference(rot_b).angle <= rot_threshold

    def _mute_mmd_tools_physics_constraints(self):
        armature = self.model.armature if self.model is not None else None
        if armature is None:
            return

        self._muted_mmd_tools_constraints = []
        for pose_bone in armature.pose.bones:
            constraint = pose_bone.constraints.get("mmd_tools_rigid_track")
            if constraint is None:
                continue
            self._muted_mmd_tools_constraints.append((constraint, bool(constraint.mute)))
            constraint.mute = True

    def _restore_mmd_tools_physics_constraints(self):
        constraints = self._muted_mmd_tools_constraints
        self._muted_mmd_tools_constraints = []
        for constraint, was_muted in constraints:
            try:
                constraint.mute = was_muted
            except ReferenceError:
                pass

    def _disconnect_physics_bones(self, context):
        armature = self.model.armature if self.model is not None else None
        if armature is None:
            return

        bone_names = {
            rigid.bone_name
            for rigid in self.model.rigid_bodies
            if rigid.mode == MODE_DYNAMIC and rigid.bone_name
        }
        if not bone_names:
            return

        def edit(edit_bones):
            for bone_name in bone_names:
                edit_bone = edit_bones.get(bone_name)
                if edit_bone is None or not edit_bone.use_connect:
                    continue
                edit_bone.use_connect = False
                self._disconnected_bone_names.add(bone_name)

        self._disconnected_armature = armature
        self._with_armature_edit_bones(context, armature, edit)

    def _restore_physics_bones(self):
        if not self._disconnected_bone_names:
            return
        armature = self._disconnected_armature
        if armature is None or armature.name not in bpy.data.objects:
            self._disconnected_armature = None
            self._disconnected_bone_names = set()
            return

        bone_names = set(self._disconnected_bone_names)

        def edit(edit_bones):
            for bone_name in bone_names:
                edit_bone = edit_bones.get(bone_name)
                if edit_bone is not None:
                    edit_bone.use_connect = True

        try:
            self._with_armature_edit_bones(bpy.context, armature, edit)
        finally:
            self._disconnected_armature = None
            self._disconnected_bone_names = set()

    @staticmethod
    def _with_armature_edit_bones(context, armature, callback):
        view_layer = context.view_layer
        active = view_layer.objects.active
        active_mode = active.mode if active is not None else "OBJECT"
        selected = list(context.selected_objects)

        try:
            if active is not None and active.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for obj in selected:
                obj.select_set(False)
            armature.select_set(True)
            view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode="EDIT")
            callback(armature.data.edit_bones)
        finally:
            if view_layer.objects.active is not None and view_layer.objects.active.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in selected:
                if obj.name in bpy.data.objects:
                    obj.select_set(True)
            if active is not None and active.name in bpy.data.objects:
                view_layer.objects.active = active
                if active_mode != "OBJECT":
                    try:
                        bpy.ops.object.mode_set(mode=active_mode)
                    except RuntimeError:
                        pass
            context.view_layer.update()
