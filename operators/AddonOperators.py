from pathlib import Path

import bpy

from ..physics import bake, debug_visual, physics_sync, pmx_data_reader


def iface_(text):
    return bpy.app.translations.pgettext_iface(text)


def _settings(context):
    return context.scene.pmx_physics


def _model_slot_roots(settings):
    return [item.root for item in settings.model_roots if item.root is not None]


def _add_model_slot(settings, root):
    if root is None:
        return False
    for item in settings.model_roots:
        if item.root == root:
            item.enabled = True
            return False
    item = settings.model_roots.add()
    item.root = root
    item.enabled = True
    settings.model_root_index = len(settings.model_roots) - 1
    return True


def _set_scan_status(settings, model, diagnostics=None):
    matched_rules = getattr(model, "zone_rules", [])
    parent_chain_corrections = int(getattr(model, "parent_chain_corrections", 0))
    summary = (
        f"{len(model.rigid_bodies)} {iface_('bodies')}, "
        f"{len(model.joints)} {iface_('joints')}, "
        f"{len(model.non_collision_pairs)} {iface_('no-collision pairs')}"
    )
    if matched_rules:
        summary += f", {iface_('rules')}: {', '.join(matched_rules)}"
    if parent_chain_corrections:
        summary += f", {parent_chain_corrections} {iface_('parent-chain fixes')}"
    warnings = []
    if diagnostics:
        warnings.extend(diagnostics.get("warnings", []))
        invalid = int(diagnostics.get("invalid_joint_count", 0))
        if invalid:
            warnings.append(f"{invalid} {iface_('invalid joints')}")
    settings.scan_summary = summary
    settings.scan_warnings = "; ".join(warnings)
    settings.perf_body_count = len(model.rigid_bodies)
    settings.perf_joint_count = len(model.joints)
    settings.perf_pair_count = len(model.non_collision_pairs)
    settings.status = summary


class PMXPHYSICS_OT_use_active_model(bpy.types.Operator):
    bl_idname = "pmx_physics.use_active_model"
    bl_label = "Use Active Model"
    bl_description = "Use the active mmd_tools model root"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        root = pmx_data_reader.find_root_object(context.active_object)
        if root is None:
            self.report({"ERROR"}, iface_("Active object is not under an mmd_tools model root"))
            return {"CANCELLED"}
        settings.model_root = root
        settings.status = f"{iface_('Selected')} {root.name}"
        return {"FINISHED"}


class PMXPHYSICS_OT_add_active_model(bpy.types.Operator):
    bl_idname = "pmx_physics.add_active_model"
    bl_label = "Add Active Model"
    bl_description = "Add the active mmd_tools model root to the independent simulation list"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        root = pmx_data_reader.find_root_object(context.active_object)
        if root is None:
            self.report({"ERROR"}, iface_("Active object is not under an mmd_tools model root"))
            return {"CANCELLED"}
        settings.model_root = root
        added = _add_model_slot(settings, root)
        action = iface_("Added") if added else iface_("Already in model list")
        settings.status = f"{action}: {root.name}"
        return {"FINISHED"}


class PMXPHYSICS_OT_remove_model_slot(bpy.types.Operator):
    bl_idname = "pmx_physics.remove_model_slot"
    bl_label = "Remove Model"
    bl_description = "Remove the selected model from the independent simulation list"
    bl_options = {"REGISTER"}

    index: bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})

    def execute(self, context):
        settings = _settings(context)
        index = int(self.index)
        if index < 0:
            index = int(settings.model_root_index)
        if index < 0 or index >= len(settings.model_roots):
            settings.status = iface_("No model list item selected")
            return {"CANCELLED"}
        root = settings.model_roots[index].root
        name = root.name if root is not None else iface_("Unknown")
        settings.model_roots.remove(index)
        settings.model_root_index = min(index, max(0, len(settings.model_roots) - 1))
        settings.status = f"{iface_('Removed')}: {name}"
        return {"FINISHED"}


class PMXPHYSICS_OT_clear_model_slots(bpy.types.Operator):
    bl_idname = "pmx_physics.clear_model_slots"
    bl_label = "Clear Models"
    bl_description = "Clear the independent simulation model list"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        count = len(settings.model_roots)
        while len(settings.model_roots):
            settings.model_roots.remove(len(settings.model_roots) - 1)
        settings.model_root_index = 0
        settings.status = f"{iface_('Cleared')} {count} {iface_('model(s)')}"
        return {"FINISHED"}


class PMXPHYSICS_OT_scan_model(bpy.types.Operator):
    bl_idname = "pmx_physics.scan_model"
    bl_label = "Scan Model"
    bl_description = "Read mmd_tools rigid bodies and joints from the selected model"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        root = settings.model_root or pmx_data_reader.find_root_object(context.active_object)
        diagnostics = pmx_data_reader.diagnose_model(context, root)
        if diagnostics["errors"]:
            settings.scan_summary = ""
            settings.scan_warnings = "; ".join(diagnostics["warnings"])
            settings.status = "; ".join(diagnostics["errors"])
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        try:
            model = pmx_data_reader.read_model(context, root)
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        settings.model_root = model.root
        _set_scan_status(settings, model, diagnostics)
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_scan_all_models(bpy.types.Operator):
    bl_idname = "pmx_physics.scan_all_models"
    bl_label = "Scan All Models"
    bl_description = "Read all enabled mmd_tools model roots in the independent simulation list"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        roots = [item.root for item in settings.model_roots if item.root is not None and item.enabled]
        if not roots:
            settings.status = iface_("No enabled models in list")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}

        total_bodies = 0
        total_joints = 0
        total_pairs = 0
        names = []
        warnings = []
        for root in roots:
            diagnostics = pmx_data_reader.diagnose_model(context, root)
            if diagnostics["errors"]:
                warnings.append(f"{root.name}: {'; '.join(diagnostics['errors'])}")
                continue
            try:
                model = pmx_data_reader.read_model(context, root)
            except Exception as exc:
                warnings.append(f"{root.name}: {exc}")
                continue
            total_bodies += len(model.rigid_bodies)
            total_joints += len(model.joints)
            total_pairs += len(model.non_collision_pairs)
            names.append(root.name)

        if not names:
            settings.status = "; ".join(warnings) if warnings else iface_("No valid models found")
            settings.scan_summary = ""
            settings.scan_warnings = settings.status
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}

        settings.perf_body_count = total_bodies
        settings.perf_joint_count = total_joints
        settings.perf_pair_count = total_pairs
        settings.scan_summary = (
            f"{len(names)} {iface_('model(s)')}, "
            f"{total_bodies} {iface_('bodies')}, "
            f"{total_joints} {iface_('joints')}, "
            f"{total_pairs} {iface_('no-collision pairs')}"
        )
        settings.scan_warnings = "; ".join(warnings)
        settings.status = settings.scan_summary
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_import_vmd(bpy.types.Operator):
    bl_idname = "pmx_physics.import_vmd"
    bl_label = "Import VMD Motion"
    bl_description = "Select the PMX model root and open mmd_tools VMD import"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        root = settings.model_root or pmx_data_reader.find_root_object(context.active_object)
        if root is None:
            settings.status = iface_("No mmd_tools model root selected")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}

        try:
            import_vmd = bpy.ops.mmd_tools.import_vmd
        except AttributeError:
            settings.status = iface_("mmd_tools VMD import operator was not found")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}

        physics_sync.force_stop()
        settings.is_running = False
        settings.model_root = root

        view_layer = context.view_layer
        try:
            for obj in context.selected_objects:
                obj.select_set(False)
            root.select_set(True)
            view_layer.objects.active = root
        except RuntimeError as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        try:
            return import_vmd("INVOKE_DEFAULT")
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class PMXPHYSICS_OT_apply_quality_preset(bpy.types.Operator):
    bl_idname = "pmx_physics.apply_quality_preset"
    bl_label = "Apply Preset"
    bl_description = "Apply the selected PMX Physics quality preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        if not settings.apply_quality_preset():
            settings.status = iface_("Unknown quality preset")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        settings.status = f"{iface_('Applied quality preset')}: {settings.quality_preset}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_apply_debug_visuals(bpy.types.Operator):
    bl_idname = "pmx_physics.apply_debug_visuals"
    bl_label = "Apply Debug Visuals"
    bl_description = "Show PMX rigid bodies and joints with physics debug colors"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        root = settings.model_root or pmx_data_reader.find_root_object(context.active_object)
        if root is None:
            settings.status = iface_("No mmd_tools model root selected")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        try:
            count = debug_visual.apply_debug_visuals(
                context,
                root,
                settings.debug_visual_mode,
                settings.debug_force_visible,
            )
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.model_root = root
        settings.status = f"{iface_('Debug visualized')} {count} {iface_('objects')}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_apply_all_debug_visuals(bpy.types.Operator):
    bl_idname = "pmx_physics.apply_all_debug_visuals"
    bl_label = "Apply All Debug Visuals"
    bl_description = "Show PMX rigid bodies and joints for all enabled models"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        roots = [item.root for item in settings.model_roots if item.root is not None and item.enabled]
        if not roots:
            root = settings.model_root or pmx_data_reader.find_root_object(context.active_object)
            if root is not None:
                roots = [root]
        if not roots:
            settings.status = iface_("No enabled models in list")
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        try:
            models, count = debug_visual.apply_debug_visuals_for_roots(
                context,
                roots,
                settings.debug_visual_mode,
                settings.debug_force_visible,
            )
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status = (
            f"{iface_('Debug visualized')} {models} {iface_('model(s)')} / "
            f"{count} {iface_('objects')}"
        )
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_clear_debug_visuals(bpy.types.Operator):
    bl_idname = "pmx_physics.clear_debug_visuals"
    bl_label = "Clear Debug Visuals"
    bl_description = "Restore display settings changed by PMX Physics debug visuals"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        count = debug_visual.clear_debug_visuals()
        settings.status = f"{iface_('Cleared debug visuals')} {count} {iface_('objects')}"
        return {"FINISHED"}


class PMXPHYSICS_OT_dump_interaction_debug(bpy.types.Operator):
    bl_idname = "pmx_physics.dump_interaction_debug"
    bl_label = "Dump Interaction Debug"
    bl_description = "Write the latest interaction diagnostics to a text report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        report_path = Path("N:/Blender-Physics/interaction_debug_report.txt")
        lines = [
            "MikuMikuPhysics Interaction Debug",
            f"Status: {settings.status}",
            f"Kind: {settings.interaction_debug_kind}",
            f"Scope: {settings.interaction_debug_scope}",
            f"Static Count: {settings.interaction_debug_static_count}",
            f"Dynamic Count: {settings.interaction_debug_dynamic_count}",
            f"Frozen Dynamic Count: {settings.interaction_debug_frozen_count}",
            f"Static Bodies: {settings.interaction_debug_static_bodies}",
            f"Dynamic Bodies: {settings.interaction_debug_dynamic_bodies}",
            f"Written Bones: {settings.interaction_debug_written_bones}",
            "",
            "Performance",
            f"Bodies: {settings.perf_body_count}",
            f"Joints: {settings.perf_joint_count}",
            f"Pairs: {settings.perf_pair_count}",
            f"Timer Tick ms: last={settings.perf_last_tick_ms:.3f}, avg={settings.perf_avg_tick_ms:.3f}, max={settings.perf_max_tick_ms:.3f}",
            f"World Step ms: last={settings.perf_last_step_ms:.3f}, avg={settings.perf_avg_step_ms:.3f}, max={settings.perf_max_step_ms:.3f}",
            f"Native ms: last={settings.perf_last_native_ms:.3f}, avg={settings.perf_avg_native_ms:.3f}, max={settings.perf_max_native_ms:.3f}",
            f"Apply ms: last={settings.perf_last_apply_ms:.3f}, avg={settings.perf_avg_apply_ms:.3f}, max={settings.perf_max_apply_ms:.3f}",
        ]
        report_path.write_text("\n".join(lines), encoding="utf-8")
        settings.status = f"Interaction debug written: {report_path}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_start(bpy.types.Operator):
    bl_idname = "pmx_physics.start"
    bl_label = "Start"
    bl_description = "Start realtime PMX physics using the external Bullet DLL"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            physics_sync.start(context, settings)
        except Exception as exc:
            settings.is_running = False
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.is_running = True
        settings.status = iface_("Running")
        return {"FINISHED"}


class PMXPHYSICS_OT_start_all(bpy.types.Operator):
    bl_idname = "pmx_physics.start_all"
    bl_label = "Start All"
    bl_description = "Start PMX physics for all enabled models in the model list"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            count = physics_sync.start_all(context, settings)
        except Exception as exc:
            settings.is_running = False
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.is_running = True
        settings.status = f"{iface_('Running')} {count} {iface_('model(s)')}"
        return {"FINISHED"}


class PMXPHYSICS_OT_stop(bpy.types.Operator):
    bl_idname = "pmx_physics.stop"
    bl_label = "Stop"
    bl_description = "Stop realtime PMX physics"
    bl_options = {"REGISTER"}

    def execute(self, context):
        physics_sync.stop()
        settings = _settings(context)
        settings.is_running = False
        settings.status = iface_("Stopped")
        return {"FINISHED"}


class PMXPHYSICS_OT_force_stop(bpy.types.Operator):
    bl_idname = "pmx_physics.force_stop"
    bl_label = "Force Stop"
    bl_description = "Force stop and clean up all PMX Physics timers and handlers"
    bl_options = {"REGISTER"}

    def execute(self, context):
        count = physics_sync.force_stop()
        settings = _settings(context)
        settings.is_running = False
        settings.status = f"{iface_('Force stopped')} {count} {iface_('controller(s)')}"
        return {"FINISHED"}


class PMXPHYSICS_OT_reset(bpy.types.Operator):
    bl_idname = "pmx_physics.reset"
    bl_label = "Reset"
    bl_description = "Stop simulation and restore the pose captured when PMX physics started"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            restored = physics_sync.reset(context, settings)
        except Exception as exc:
            settings.is_running = False
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.is_running = False
        settings.status = iface_("Reset") if restored else iface_("Reset: simulation is not running")
        return {"FINISHED"}


class PMXPHYSICS_OT_step(bpy.types.Operator):
    bl_idname = "pmx_physics.step"
    bl_label = "Step"
    bl_description = "Step the PMX physics world once"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            physics_sync.step_once(context, settings)
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status = iface_("Stepped")
        return {"FINISHED"}


class PMXPHYSICS_OT_bake(bpy.types.Operator):
    bl_idname = "pmx_physics.bake"
    bl_label = "Bake"
    bl_description = "Bake Bullet-driven physics bones to Blender keyframes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        window_manager = context.window_manager
        progress_active = False
        try:
            window_manager.progress_begin(0, bake.bake_frame_total(settings))
            progress_active = True
            count = bake.bake_to_keyframes(
                context,
                settings,
                progress=lambda done, _total, _frame: window_manager.progress_update(done),
            )
        except Exception as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        finally:
            if progress_active:
                window_manager.progress_end()
        settings.status = f"{iface_('Baked')} {count} {iface_('frames')}"
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}


class PMXPHYSICS_OT_compare_bake(bpy.types.Operator):
    bl_idname = "pmx_physics.compare_bake"
    bl_label = "Compare Bake"
    bl_description = "Compare current baked keyframes with a fresh Bullet simulation over the bake range"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            result = bake.compare_baked_motion(context, settings)
        except Exception as exc:
            settings.bake_compare_summary = str(exc)
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        settings.bake_compare_summary = (
            f"{iface_('Samples')}: {result['samples']}, "
            f"{iface_('Avg Loc')}: {result['avg_loc']:.5f}, "
            f"{iface_('Max Loc')}: {result['max_loc']:.5f}, "
            f"{iface_('Avg Rot')}: {result['avg_angle_deg']:.3f} deg, "
            f"{iface_('Max Rot')}: {result['max_angle_deg']:.3f} deg"
        )
        settings.status = settings.bake_compare_summary
        self.report({"INFO"}, settings.status)
        return {"FINISHED"}
