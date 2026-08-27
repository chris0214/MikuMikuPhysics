import bpy

from .physics_world import PhysicsWorld, capture_initial_snapshot, restore_snapshot


def _scene_fps(scene):
    return scene.render.fps / scene.render.fps_base


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


def _insert_bone_keyframes(armature, bone_names):
    for bone_name in bone_names:
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        pose_bone.keyframe_insert(data_path="location")
        if pose_bone.rotation_mode == "QUATERNION":
            pose_bone.keyframe_insert(data_path="rotation_quaternion")
        elif pose_bone.rotation_mode == "AXIS_ANGLE":
            pose_bone.keyframe_insert(data_path="rotation_axis_angle")
        else:
            pose_bone.keyframe_insert(data_path="rotation_euler")
        pose_bone.keyframe_insert(data_path="scale")


def _bone_frame_samples(armature, bone_names, start, end, scene):
    samples = {}
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        for bone_name in bone_names:
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is not None:
                samples[(frame, bone_name)] = pose_bone.matrix.copy()
    return samples


def compare_baked_motion(context, settings):
    scene = context.scene
    root = settings.model_root
    if root is None:
        from . import pmx_data_reader

        root = pmx_data_reader.find_root_object(context.active_object)
    from . import pmx_data_reader

    model = pmx_data_reader.read_model(context, root)
    if model.armature is None:
        raise RuntimeError("Selected model has no armature to compare")

    start = int(settings.bake_start)
    end = int(settings.bake_end)
    if end < start:
        raise RuntimeError("Bake end frame must be greater than or equal to start frame")

    bone_names = []
    for rigid in model.rigid_bodies:
        if rigid.bone_name and rigid.bone_name not in bone_names:
            bone_names.append(rigid.bone_name)
    if not bone_names:
        raise RuntimeError("No rigid-body-linked bones were found to compare")

    current_frame = scene.frame_current
    current_samples = _bone_frame_samples(model.armature, bone_names, start, end, scene)
    world = PhysicsWorld()
    max_loc = 0.0
    sum_loc = 0.0
    max_angle = 0.0
    sum_angle = 0.0
    sample_count = 0
    try:
        scene.frame_set(start)
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
            0,
            settings.locked_joint_pullback,
            settings.resting_body_stabilization,
        )
        fps = _scene_fps(scene)
        seconds_per_frame = 1.0 / fps
        substeps_per_frame = max(1, round(seconds_per_frame / _fixed_timestep(settings)))
        timestep = seconds_per_frame / substeps_per_frame

        for _ in range(int(settings.bake_preroll) * substeps_per_frame):
            world.step(timestep * _time_scale(settings), 1)

        for frame in range(start, end + 1):
            scene.frame_set(frame)
            world.flush_depsgraph()
            for _ in range(substeps_per_frame):
                world.step(timestep * _time_scale(settings), 1)
            world.flush_depsgraph()

            for bone_name in bone_names:
                pose_bone = model.armature.pose.bones.get(bone_name)
                baseline = current_samples.get((frame, bone_name))
                if pose_bone is None or baseline is None:
                    continue
                loc_a, rot_a, _scale_a = baseline.decompose()
                loc_b, rot_b, _scale_b = pose_bone.matrix.decompose()
                loc_delta = (loc_b - loc_a).length
                angle_delta = rot_a.rotation_difference(rot_b).angle
                max_loc = max(max_loc, loc_delta)
                sum_loc += loc_delta
                max_angle = max(max_angle, angle_delta)
                sum_angle += angle_delta
                sample_count += 1
    finally:
        world.destroy(restore_initial=True)
        scene.frame_set(current_frame)

    if sample_count == 0:
        raise RuntimeError("No comparable baked bone samples were found")
    return {
        "samples": sample_count,
        "avg_loc": sum_loc / sample_count,
        "max_loc": max_loc,
        "avg_angle_deg": (sum_angle / sample_count) * 57.29577951308232,
        "max_angle_deg": max_angle * 57.29577951308232,
    }


def bake_frame_total(settings):
    """Total progress units for a bake: preroll frames plus baked frames."""
    preroll = int(getattr(settings, "bake_preroll", 0))
    return preroll + int(settings.bake_end) - int(settings.bake_start) + 1


def bake_to_keyframes(context, settings, progress=None):
    scene = context.scene
    start = int(settings.bake_start)
    end = int(settings.bake_end)
    if end < start:
        raise RuntimeError("Bake end frame must be greater than or equal to start frame")

    current_frame = scene.frame_current
    scene.frame_set(start)

    world = PhysicsWorld()
    root = settings.model_root
    if root is None:
        from . import pmx_data_reader

        root = pmx_data_reader.find_root_object(context.active_object)

    pre_bake_snapshot = None
    try:
        from . import pmx_data_reader

        pre_model = pmx_data_reader.read_model(context, root)
        pre_bake_snapshot = capture_initial_snapshot(pre_model)

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
            0,
            settings.locked_joint_pullback,
            settings.resting_body_stabilization,
        )
        if world.model.armature is None:
            raise RuntimeError("Selected model has no armature to bake")

        fps = _scene_fps(scene)
        seconds_per_frame = 1.0 / fps
        substeps_per_frame = max(1, round(seconds_per_frame / _fixed_timestep(settings)))
        timestep = seconds_per_frame / substeps_per_frame
        bone_names = world.dynamic_bone_names()

        scene.frame_set(start)
        world.flush_depsgraph()
        preroll_frames = int(settings.bake_preroll)
        for frame_index in range(preroll_frames):
            for _ in range(substeps_per_frame):
                world.step(timestep * _time_scale(settings), 1)
            if progress is not None:
                progress(frame_index + 1, bake_frame_total(settings), None)
        world.flush_depsgraph()

        frame_count = end - start + 1
        for frame_offset, frame in enumerate(range(start, end + 1)):
            scene.frame_set(frame)
            world.flush_depsgraph()
            for _ in range(substeps_per_frame):
                world.step(timestep * _time_scale(settings), 1)
            world.flush_depsgraph()
            _insert_bone_keyframes(world.model.armature, bone_names)
            if progress is not None:
                progress(preroll_frames + frame_offset + 1, bake_frame_total(settings), frame)
    finally:
        world.destroy()
        scene.frame_set(current_frame)
        if bool(settings.bake_restore_after):
            restore_snapshot(pre_bake_snapshot, getattr(context, "view_layer", None))

    return end - start + 1
