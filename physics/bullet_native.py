import ctypes
import os
import sys

from mathutils import Quaternion, Vector

from . import transforms


EXPECTED_API_VERSION = 9


class NativeError(RuntimeError):
    pass


class NativeRigidDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_int),
        ("shape", ctypes.c_int),
        ("mode", ctypes.c_int),
        ("size", ctypes.c_float * 3),
        ("mass", ctypes.c_float),
        ("friction", ctypes.c_float),
        ("restitution", ctypes.c_float),
        ("linear_damping", ctypes.c_float),
        ("angular_damping", ctypes.c_float),
        ("collision_group", ctypes.c_uint16),
        ("collision_mask", ctypes.c_uint16),
        ("position", ctypes.c_float * 3),
        ("rotation", ctypes.c_float * 4),
    ]


class NativeJointDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_int),
        ("rigid_a", ctypes.c_int),
        ("rigid_b", ctypes.c_int),
        ("disable_collisions", ctypes.c_int),
        ("position", ctypes.c_float * 3),
        ("rotation", ctypes.c_float * 4),
        ("linear_lower", ctypes.c_float * 3),
        ("linear_upper", ctypes.c_float * 3),
        ("angular_lower", ctypes.c_float * 3),
        ("angular_upper", ctypes.c_float * 3),
        ("spring_linear", ctypes.c_float * 3),
        ("spring_linear_damping", ctypes.c_float * 3),
        ("spring_angular", ctypes.c_float * 3),
        ("spring_angular_damping", ctypes.c_float * 3),
        ("joint_stop_erp", ctypes.c_float),
        ("joint_stop_cfm", ctypes.c_float),
        ("locked_joint_stop_erp", ctypes.c_float),
        ("locked_joint_stop_cfm", ctypes.c_float),
    ]


class NativeBodyTransform(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_int),
        ("position", ctypes.c_float * 3),
        ("rotation", ctypes.c_float * 4),
    ]


class NativeNonCollisionPair(ctypes.Structure):
    _fields_ = [
        ("rigid_a", ctypes.c_int),
        ("rigid_b", ctypes.c_int),
    ]


class NativeModelPair(ctypes.Structure):
    _fields_ = [
        ("model_a", ctypes.c_int),
        ("model_b", ctypes.c_int),
    ]


class NativeBodyPair(ctypes.Structure):
    _fields_ = [
        ("body_a", ctypes.c_int),
        ("body_b", ctypes.c_int),
    ]


def _fill3(target, values):
    for index in range(3):
        target[index] = float(values[index])


def _fill4(target, values):
    for index in range(4):
        target[index] = float(values[index])


def _matrix_to_native_transform(matrix, index):
    position, rotation = transforms.blender_matrix_to_pmx_transform(matrix)
    result = NativeBodyTransform()
    result.index = int(index)
    _fill3(result.position, position)
    _fill4(result.rotation, (rotation.x, rotation.y, rotation.z, rotation.w))
    return result


class BulletNative:
    def __init__(self, dll_path=None):
        self.dll_path = os.path.abspath(dll_path) if dll_path else ""
        self.lib = self._load_library()
        self.handle = None
        self._bind()

    def _load_library(self):
        try:
            process_lib = ctypes.CDLL(sys.executable if os.name == "nt" else None)
            getattr(process_lib, "pmx_bullet_api_version")
            self.dll_path = "<Blender internal>"
            return process_lib
        except (AttributeError, OSError):
            pass

        if not self.dll_path:
            raise NativeError("Internal PMX Bullet runtime not found and no Bullet DLL path was provided")
        if not os.path.exists(self.dll_path):
            raise NativeError(f"Bullet DLL not found: {self.dll_path}")
        return ctypes.CDLL(self.dll_path)

    def _bind(self):
        lib = self.lib
        lib.pmx_bullet_api_version.restype = ctypes.c_int
        api_version = int(lib.pmx_bullet_api_version())
        if api_version != EXPECTED_API_VERSION:
            raise NativeError(f"Bullet DLL API version mismatch: expected {EXPECTED_API_VERSION}, got {api_version}")
        lib.pmx_bullet_create_world.restype = ctypes.c_void_p
        lib.pmx_bullet_destroy_world.argtypes = [ctypes.c_void_p]
        lib.pmx_bullet_set_gravity.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        lib.pmx_bullet_set_solver_iterations.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.pmx_bullet_set_solver_iterations.restype = ctypes.c_int
        lib.pmx_bullet_set_joint_quality.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        lib.pmx_bullet_set_joint_quality.restype = ctypes.c_int
        lib.pmx_bullet_set_stabilization.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.pmx_bullet_set_stabilization.restype = ctypes.c_int
        lib.pmx_bullet_add_rigid_bodies.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeRigidDesc), ctypes.c_int]
        lib.pmx_bullet_add_rigid_bodies.restype = ctypes.c_int
        lib.pmx_bullet_set_body_model_ids.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.pmx_bullet_set_body_model_ids.restype = ctypes.c_int
        lib.pmx_bullet_set_disabled_model_pairs.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeModelPair), ctypes.c_int]
        lib.pmx_bullet_set_disabled_model_pairs.restype = ctypes.c_int
        lib.pmx_bullet_set_cross_model_body_pair_filter_enabled.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.pmx_bullet_set_cross_model_body_pair_filter_enabled.restype = ctypes.c_int
        lib.pmx_bullet_set_enabled_cross_model_body_pairs.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeBodyPair), ctypes.c_int]
        lib.pmx_bullet_set_enabled_cross_model_body_pairs.restype = ctypes.c_int
        lib.pmx_bullet_add_non_collision_pairs.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeNonCollisionPair), ctypes.c_int]
        lib.pmx_bullet_add_non_collision_pairs.restype = ctypes.c_int
        lib.pmx_bullet_add_joints.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeJointDesc), ctypes.c_int]
        lib.pmx_bullet_add_joints.restype = ctypes.c_int
        lib.pmx_bullet_temporal_kinematic_init.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeBodyTransform), ctypes.c_int]
        lib.pmx_bullet_temporal_kinematic_init.restype = ctypes.c_int
        lib.pmx_bullet_set_kinematic_transforms.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeBodyTransform), ctypes.c_int]
        lib.pmx_bullet_set_kinematic_transforms.restype = ctypes.c_int
        lib.pmx_bullet_freeze_body_transforms.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeBodyTransform), ctypes.c_int]
        lib.pmx_bullet_freeze_body_transforms.restype = ctypes.c_int
        lib.pmx_bullet_step.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_int]
        lib.pmx_bullet_step.restype = ctypes.c_int
        lib.pmx_bullet_get_body_transforms.argtypes = [ctypes.c_void_p, ctypes.POINTER(NativeBodyTransform), ctypes.c_int]
        lib.pmx_bullet_get_body_transforms.restype = ctypes.c_int
        lib.pmx_bullet_reset.argtypes = [ctypes.c_void_p]
        lib.pmx_bullet_reset.restype = ctypes.c_int
        lib.pmx_bullet_prewarm.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_float]
        lib.pmx_bullet_prewarm.restype = ctypes.c_int

    def create_world(self):
        self.handle = self.lib.pmx_bullet_create_world()
        if not self.handle:
            raise NativeError("pmx_bullet_create_world returned null")

    def destroy(self):
        if self.handle:
            self.lib.pmx_bullet_destroy_world(self.handle)
            self.handle = None

    def _check(self, ok, action):
        if not ok:
            raise NativeError(f"Native Bullet call failed: {action}")

    def set_gravity(self, gravity):
        pmx_gravity = transforms.blender_vector_to_pmx(Vector(gravity))
        self.lib.pmx_bullet_set_gravity(
            self.handle,
            float(pmx_gravity.x),
            float(pmx_gravity.y),
            float(pmx_gravity.z),
        )

    def set_solver_iterations(self, iterations):
        self._check(
            self.lib.pmx_bullet_set_solver_iterations(self.handle, int(iterations)),
            "set_solver_iterations",
        )

    def set_joint_quality(
        self,
        use_frame_offset,
        joint_stop_erp,
        joint_stop_cfm,
        locked_joint_stop_erp,
        locked_joint_stop_cfm,
    ):
        self._check(
            self.lib.pmx_bullet_set_joint_quality(
                self.handle,
                1 if use_frame_offset else 0,
                float(joint_stop_erp),
                float(joint_stop_cfm),
                float(locked_joint_stop_erp),
                float(locked_joint_stop_cfm),
            ),
            "set_joint_quality",
        )

    def set_stabilization(self, locked_joint_pullback, resting_body_stabilization):
        self._check(
            self.lib.pmx_bullet_set_stabilization(
                self.handle,
                1 if locked_joint_pullback else 0,
                1 if resting_body_stabilization else 0,
            ),
            "set_stabilization",
        )

    def add_rigid_bodies(self, model, initial_matrices=None):
        initial_matrices = initial_matrices or {}
        array_type = NativeRigidDesc * len(model.rigid_bodies)
        array = array_type()
        for array_index, rigid in enumerate(model.rigid_bodies):
            desc = array[array_index]
            desc.index = rigid.index
            desc.shape = rigid.shape
            desc.mode = rigid.mode
            _fill3(desc.size, rigid.size)
            desc.mass = float(rigid.mass)
            desc.friction = float(rigid.friction)
            desc.restitution = float(rigid.restitution)
            desc.linear_damping = float(rigid.linear_damping)
            desc.angular_damping = float(rigid.angular_damping)
            desc.collision_group = ctypes.c_uint16(1 << rigid.collision_group_number).value
            desc.collision_mask = ctypes.c_uint16(0xFFFF & ~rigid.no_collision_mask).value
            matrix = initial_matrices.get(rigid.index, rigid.local_matrix)
            position, rotation = transforms.blender_matrix_to_pmx_transform(matrix)
            _fill3(desc.position, position)
            _fill4(desc.rotation, (rotation.x, rotation.y, rotation.z, rotation.w))
        self._check(self.lib.pmx_bullet_add_rigid_bodies(self.handle, array, len(array)), "add_rigid_bodies")

    def set_body_model_ids(self, start_body, count, model_index):
        self._check(
            self.lib.pmx_bullet_set_body_model_ids(
                self.handle,
                int(start_body),
                int(count),
                int(model_index),
            ),
            "set_body_model_ids",
        )

    def set_disabled_model_pairs(self, pairs):
        pairs = list(pairs or [])
        if not pairs:
            self._check(
                self.lib.pmx_bullet_set_disabled_model_pairs(self.handle, None, 0),
                "set_disabled_model_pairs",
            )
            return
        array_type = NativeModelPair * len(pairs)
        array = array_type()
        for index, (model_a, model_b) in enumerate(pairs):
            array[index].model_a = int(model_a)
            array[index].model_b = int(model_b)
        self._check(
            self.lib.pmx_bullet_set_disabled_model_pairs(self.handle, array, len(array)),
            "set_disabled_model_pairs",
        )

    def set_cross_model_body_pair_filter_enabled(self, enabled):
        self._check(
            self.lib.pmx_bullet_set_cross_model_body_pair_filter_enabled(
                self.handle,
                1 if enabled else 0,
            ),
            "set_cross_model_body_pair_filter_enabled",
        )

    def set_enabled_cross_model_body_pairs(self, pairs):
        pairs = list(pairs or [])
        if not pairs:
            self._check(
                self.lib.pmx_bullet_set_enabled_cross_model_body_pairs(self.handle, None, 0),
                "set_enabled_cross_model_body_pairs",
            )
            return
        array_type = NativeBodyPair * len(pairs)
        array = array_type()
        for index, (body_a, body_b) in enumerate(pairs):
            array[index].body_a = int(body_a)
            array[index].body_b = int(body_b)
        self._check(
            self.lib.pmx_bullet_set_enabled_cross_model_body_pairs(self.handle, array, len(array)),
            "set_enabled_cross_model_body_pairs",
        )

    def add_non_collision_pairs(self, model):
        pairs = model.non_collision_pairs
        if not pairs:
            return
        array_type = NativeNonCollisionPair * len(pairs)
        array = array_type()
        for index, (rigid_a, rigid_b) in enumerate(pairs):
            array[index].rigid_a = int(rigid_a)
            array[index].rigid_b = int(rigid_b)
        self._check(
            self.lib.pmx_bullet_add_non_collision_pairs(self.handle, array, len(array)),
            "add_non_collision_pairs",
        )

    def add_joints(self, model):
        array_type = NativeJointDesc * len(model.joints)
        array = array_type()
        for array_index, joint in enumerate(model.joints):
            desc = array[array_index]
            desc.index = joint.index
            desc.rigid_a = joint.rigid_a_index
            desc.rigid_b = joint.rigid_b_index
            desc.disable_collisions = int(joint.disable_collisions)
            position, rotation = transforms.blender_matrix_to_pmx_transform(joint.local_matrix)
            _fill3(desc.position, position)
            _fill4(desc.rotation, (rotation.x, rotation.y, rotation.z, rotation.w))
            _fill3(desc.linear_lower, joint.linear_lower)
            _fill3(desc.linear_upper, joint.linear_upper)
            _fill3(desc.angular_lower, joint.angular_lower)
            _fill3(desc.angular_upper, joint.angular_upper)
            _fill3(desc.spring_linear, joint.spring_linear)
            _fill3(desc.spring_linear_damping, joint.spring_linear_damping)
            _fill3(desc.spring_angular, joint.spring_angular)
            _fill3(desc.spring_angular_damping, joint.spring_angular_damping)
            desc.joint_stop_erp = float(getattr(joint, "joint_stop_erp", -1.0))
            desc.joint_stop_cfm = float(getattr(joint, "joint_stop_cfm", -1.0))
            desc.locked_joint_stop_erp = float(getattr(joint, "locked_joint_stop_erp", -1.0))
            desc.locked_joint_stop_cfm = float(getattr(joint, "locked_joint_stop_cfm", -1.0))
        self._check(self.lib.pmx_bullet_add_joints(self.handle, array, len(array)), "add_joints")

    def temporal_kinematic_init(self, transforms_by_index):
        array = self._build_transform_array(transforms_by_index)
        self._check(
            self.lib.pmx_bullet_temporal_kinematic_init(self.handle, array, len(array)),
            "temporal_kinematic_init",
        )

    def set_kinematic_transforms(self, transforms_by_index):
        if not transforms_by_index:
            return
        array = self._build_transform_array(transforms_by_index)
        self._check(
            self.lib.pmx_bullet_set_kinematic_transforms(self.handle, array, len(array)),
            "set_kinematic_transforms",
        )

    def freeze_body_transforms(self, transforms_by_index):
        if not transforms_by_index:
            return
        array = self._build_transform_array(transforms_by_index)
        self._check(
            self.lib.pmx_bullet_freeze_body_transforms(self.handle, array, len(array)),
            "freeze_body_transforms",
        )

    def _build_transform_array(self, transforms_by_index):
        items = sorted(transforms_by_index.items())
        array_type = NativeBodyTransform * len(items)
        array = array_type()
        for offset, (body_index, matrix) in enumerate(items):
            array[offset] = _matrix_to_native_transform(matrix, body_index)
        return array

    def step(self, timestep, max_substeps):
        self._check(
            self.lib.pmx_bullet_step(self.handle, float(timestep), int(max_substeps)),
            "step",
        )

    def get_body_transforms(self, count, wanted_indices=None):
        array_type = NativeBodyTransform * count
        array = array_type()
        self._check(
            self.lib.pmx_bullet_get_body_transforms(self.handle, array, count),
            "get_body_transforms",
        )
        if wanted_indices is not None:
            wanted = set(wanted_indices)
        else:
            wanted = None
        result = {}
        for item in array:
            if wanted is not None and item.index not in wanted:
                continue
            quat = Quaternion((item.rotation[3], item.rotation[0], item.rotation[1], item.rotation[2]))
            position = (item.position[0], item.position[1], item.position[2])
            result[item.index] = transforms.pmx_transform_to_blender_matrix(position, quat)
        return result

    def reset(self):
        self._check(self.lib.pmx_bullet_reset(self.handle), "reset")

    def prewarm(self, steps, timestep):
        steps = int(steps)
        if steps < 0:
            return
        self._check(
            self.lib.pmx_bullet_prewarm(self.handle, steps, float(timestep)),
            "prewarm",
        )
