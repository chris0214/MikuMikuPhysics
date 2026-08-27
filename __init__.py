bl_info = {
    "name": "MikuMikuPhysics",
    "author": "克里斯提亚娜",
    "maintainer": "克里斯提亚娜",
    "version": (2, 2, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MMP",
    "description": "External Bullet 2.82 runtime for mmd_tools PMX rigid bodies",
    "category": "lagcay",
    "license": "GPL-3.0-or-later",
}

import bpy

from . import config, localization
from .operators import AddonOperators
from .panels import AddonPanels


CLASSES = (
    config.PMXPhysicsModelSlot,
    config.PMXPhysicsSettings,
    AddonOperators.PMXPHYSICS_OT_use_active_model,
    AddonOperators.PMXPHYSICS_OT_add_active_model,
    AddonOperators.PMXPHYSICS_OT_remove_model_slot,
    AddonOperators.PMXPHYSICS_OT_clear_model_slots,
    AddonOperators.PMXPHYSICS_OT_scan_model,
    AddonOperators.PMXPHYSICS_OT_scan_all_models,
    AddonOperators.PMXPHYSICS_OT_import_vmd,
    AddonOperators.PMXPHYSICS_OT_apply_quality_preset,
    AddonOperators.PMXPHYSICS_OT_apply_debug_visuals,
    AddonOperators.PMXPHYSICS_OT_apply_all_debug_visuals,
    AddonOperators.PMXPHYSICS_OT_clear_debug_visuals,
    AddonOperators.PMXPHYSICS_OT_dump_interaction_debug,
    AddonOperators.PMXPHYSICS_OT_start,
    AddonOperators.PMXPHYSICS_OT_start_all,
    AddonOperators.PMXPHYSICS_OT_stop,
    AddonOperators.PMXPHYSICS_OT_force_stop,
    AddonOperators.PMXPHYSICS_OT_reset,
    AddonOperators.PMXPHYSICS_OT_step,
    AddonOperators.PMXPHYSICS_OT_bake,
    AddonOperators.PMXPHYSICS_OT_compare_bake,
    AddonPanels.PMXPHYSICS_PT_main,
)


def register():
    localization.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.pmx_physics = bpy.props.PointerProperty(type=config.PMXPhysicsSettings)


def unregister():
    from .physics import physics_sync

    physics_sync.stop()
    if hasattr(bpy.types.Scene, "pmx_physics"):
        del bpy.types.Scene.pmx_physics
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    localization.unregister()
