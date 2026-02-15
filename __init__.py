bl_info = {
    "name": "StrandKit - Hair Card Texture Switcher",
    "author": "Nino Defoq",
    "version": (1, 0, 3),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > StrandKit",
    "description": "Switches hair card textures based on folder structure and bakes maps.",
    "category": "Material",
}

import bpy
import shutil
import os
import gpu
from gpu.types import GPUVertFormat, GPUVertBuf
from gpu.shader import from_builtin
from bpy.app.handlers import persistent  # <--- ADD THIS LINE HERE
from . import addon_updater_ops
from bpy.props import (
    BoolProperty,
    IntProperty,
    FloatProperty,
    StringProperty,
    EnumProperty,
    PointerProperty
)

# ------------------------------------------------------------------------
# Preferences
# ------------------------------------------------------------------------

class StrandKitPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    
    downloaded_asset_files: StringProperty(
        name="Downloaded Asset Files",
        description="Semicolon-separated list of expected asset files",
        default="",
        options={'HIDDEN'}
    )
    
    bpy.types.Scene.strandkit_show_swapping = BoolProperty(default=True)
    bpy.types.Scene.strandkit_show_baking = BoolProperty(default=True)
    
    bpy.types.Scene.strandkit_show_setup = BoolProperty(
        name="Show StrandKit Setup",
        description="Show setup and update options for StrandKit",
        default=False,
    )

    # — existing add-on updater prefs —
    auto_check_update: BoolProperty(
        name="Auto-check for Updates",
        description="If enabled, checks for code updates automatically",
        default=True,
    )
    updater_interval_months: IntProperty(
        name="Months", default=0, min=0,
        description="Months between code-update checks",
    )
    updater_interval_days: IntProperty(
        name="Days", default=7, min=0, max=31,
        description="Days between code-update checks",
    )
    updater_interval_hours: IntProperty(
        name="Hours", default=0, min=0, max=23,
        description="Hours between code-update checks",
    )
    updater_interval_minutes: IntProperty(
        name="Minutes", default=0, min=0, max=59,
        description="Minutes between code-update checks",
    )
    
    asset_download_progress: FloatProperty(
        name="Download Progress",
        description="Internal: fraction of the asset download (0.0–1.0)",
        default=0.0,
        min=0.0,
        max=1.0,
    )

    # — asset-library prefs —
    asset_dir: StringProperty(
        name="Library Location",
        description="Where the .blend + .txt assets live",
        subtype='DIR_PATH',
        default="//strandkit_assets/",
    )
    asset_remote_tag: StringProperty(
        name="Latest Tag",
        description="GitHub’s latest release tag for the assets",
        default="",
    )
    
    asset_last_tag: StringProperty(
        name="Installed Tag",
        description="Version tag of the last downloaded asset library",
        default="1.0.0",
    )
    
    asset_status: StringProperty(
        name="Status",
        description="Outcome of the last asset-check",
        default="Waiting for check",
    )
    github_token: StringProperty(
        name="GitHub Token",
        description="Optional: personal token to avoid rate limits",
        default="",
        subtype='PASSWORD',
    )

    def draw(self, context):
        layout = self.layout
        addon_updater_ops.update_settings_ui(self, context)
        layout.separator()
        box = layout.box()
        box.label(text="StrandKit Asset Library:")
        box.prop(self, "asset_dir")
        box.prop(self, "asset_remote_tag")
        box.prop(self, "asset_status")
        box.prop(self, "github_token")

# ------------------------------------------------------------------------
# Properties & Utilities
# ------------------------------------------------------------------------

def list_dirs(path):
    try:
        return [d for d in sorted(os.listdir(path)) if os.path.isdir(os.path.join(path, d))]
    except:
        return []

class HairCardSwitcherProperties(bpy.types.PropertyGroup):
    
    bake_progress: FloatProperty(
        name        = "Bake Progress",
        description = "0-1 fraction of the current bake",
        default     = 0.0, min = 0.0, max = 1.0,
        options     = {'HIDDEN'}
    )
    
    material: PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Select the material to update textures in"
    )
    base_path: StringProperty(
        name="Hair Card Folder",
        subtype='DIR_PATH'
    )
    bake_width: IntProperty(
        name="Bake Width",
        description="Width (px) for baking",
        default=2048
    )
    bake_height: IntProperty(
        name="Bake Height",
        description="Height (px) for baking",
        default=2048
    )
    bake_path: StringProperty(
        name="Bake Output Folder",
        subtype='DIR_PATH',
        description="Directory to save baked textures"
    )
    
    def get_hair_types(self, context):
        return [(d, d, "") for d in list_dirs(bpy.path.abspath(self.base_path))] or [("NONE","No Types","")]
    def get_colors(self, context):
        try:
            p = os.path.join(bpy.path.abspath(self.base_path), self.hair_type)
            return [(d, d, "") for d in list_dirs(p)] or [("NONE","No Colors","")]
        except:
            return [("NONE","Invalid","")]
    def get_thicknesses(self, context):
        try:
            p = os.path.join(bpy.path.abspath(self.base_path), self.hair_type, self.color)
            return [(d, d, "") for d in list_dirs(p)] or [("NONE","No Thickness","")]
        except:
            return [("NONE","Invalid","")]
    def get_densities(self, context):
        try:
            p = os.path.join(bpy.path.abspath(self.base_path), self.hair_type, self.color, self.thickness)
            return [(d, d, "") for d in list_dirs(p)] or [("NONE","No Densities","")]
        except:
            return [("NONE","Invalid","")]

    hair_type: EnumProperty(name="Hair Type", items=get_hair_types)
    color: EnumProperty(name="Color", items=get_colors)
    thickness: EnumProperty(name="Thickness", items=get_thicknesses)
    density: EnumProperty(name="Density", items=get_densities)

# ------------------------------------------------------------------------
# UI Panel
# ------------------------------------------------------------------------

class HAIRCARD_PT_Switcher(bpy.types.Panel):
    bl_label = "StrandKit"
    bl_idname = "HAIRCARD_PT_switcher"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'StrandKit'

    def draw(self, context):
        if "StrandKit" in bpy.context.preferences.addons:
            verify_asset_library()
            
        layout = self.layout
        props = context.scene.haircard_switcher
        prefs = context.preferences.addons['StrandKit'].preferences

        # --- Setup / Updates ---
        box = layout.box()
        row = box.row()
        row.prop(context.scene, "strandkit_show_setup", text="", icon="TRIA_DOWN" if context.scene.strandkit_show_setup else "TRIA_RIGHT", emboss=False)
        row.label(text="StrandKit Setup & Updates")

        if context.scene.strandkit_show_setup:
            col = box.column(align=True)
            col.prop(prefs, "asset_dir")
            col.operator("strandkit.check_assets", text="Check Asset Library", icon='VIEWZOOM')
            
            sub = col.row()
            sub.scale_y = 0.8
            sub.label(text=f"Status: {prefs.asset_status}")

            if prefs.asset_remote_tag and prefs.asset_remote_tag != prefs.asset_last_tag:
                op = col.operator("strandkit.download_assets_progress", text=f"Download ({prefs.asset_remote_tag})", icon='FILE_REFRESH')
                op.github_token = prefs.github_token
                op.asset_dir = prefs.asset_dir
            else:
                col.label(text="Library Up to Date", icon='CHECKMARK')

            prog = prefs.asset_download_progress
            if 0.0 < prog < 1.0:
                col.label(text="Downloading...")
                col.progress(factor=prog, text=f"{int(prog * 100)}%")

            col.separator()
            
            # --- Check if already registered ---
            is_registered = False
            # Normalize paths for accurate comparison
            abs_dir = os.path.normpath(os.path.abspath(bpy.path.abspath(prefs.asset_dir)))
            
            for lib in context.preferences.filepaths.asset_libraries:
                lib_path = os.path.normpath(os.path.abspath(bpy.path.abspath(lib.path)))
                if lib_path == abs_dir:
                    is_registered = True
                    break
            
            if not is_registered:
                col.operator("strandkit.setup_asset_library", text="Register as Asset Library", icon='ASSET_MANAGER')
            else:
                col.label(text="Library Registered", icon='CHECKMARK')

        # --- Swapping ---
        box = layout.box()
        row = box.row()
        row.prop(context.scene, "strandkit_show_swapping", text="", icon="TRIA_DOWN" if context.scene.strandkit_show_swapping else "TRIA_RIGHT", emboss=False)
        row.label(text="Hair Card Swapping")

        if context.scene.strandkit_show_swapping:
            col = box.column(align=True)
            col.prop(props, "base_path")
            if props.base_path:
                col.separator()
                col.prop(props, "hair_type")
                if props.hair_type != "NONE":
                    col.prop(props, "color")
                    if props.color != "NONE":
                        col.prop(props, "thickness")
                        if props.thickness != "NONE":
                            col.prop(props, "density")
                col.separator()
                col.prop(props, "material")
                col.operator("haircard.swap_textures", icon='FILE_REFRESH')

        # --- Baking ---
        box = layout.box()
        row = box.row()
        row.prop(context.scene, "strandkit_show_baking", text="", icon="TRIA_DOWN" if context.scene.strandkit_show_baking else "TRIA_RIGHT", emboss=False)
        row.label(text="Hair Card Baking")

        if context.scene.strandkit_show_baking:
            col = box.column(align=True)
            if props.bake_width and props.bake_height:
                col.prop(props, "bake_path")
                col.operator("haircard.bake_textures", icon='RENDER_STILL')
                
                prog = props.bake_progress
                if 0.0 < prog < 1.0:
                    col.label(text="Baking textures…")
                    col.progress(factor=prog, text=f"{int(prog*100)}%")

# ------------------------------------------------------------------------
# Operators
# ------------------------------------------------------------------------

def verify_asset_library():
    prefs = bpy.context.preferences.addons[__package__].preferences
    asset_dir = bpy.path.abspath(prefs.asset_dir)
    if not isinstance(prefs.downloaded_asset_files, str) or not prefs.downloaded_asset_files.strip():
        return
    expected_files = prefs.downloaded_asset_files.split(";")
    missing = any(not os.path.exists(os.path.join(asset_dir, f)) for f in expected_files)
    if missing:
        prefs.asset_last_tag = ""
        prefs.asset_status = "Files missing – please (re)download"
    else:
        if prefs.asset_last_tag == prefs.asset_remote_tag:
            prefs.asset_status = f"Up to date ({prefs.asset_last_tag})"

class HAIRCARD_OT_SwapTextures(bpy.types.Operator):
    bl_idname = "haircard.swap_textures"
    bl_label = "Swap Hair Card Textures"
    bl_description = "Swap textures based on selected folders and detect bake size"

    def execute(self, context):
        props = context.scene.haircard_switcher
        folder = os.path.join(bpy.path.abspath(props.base_path), props.hair_type, props.color, props.thickness, props.density)
        expected = {t:None for t in ["Diffuse","Roughness","Specular","Normal","Depth","Startmask"]}
        
        if not os.path.exists(folder):
            self.report({'ERROR'}, "Path does not exist")
            return {'CANCELLED'}

        for f in os.listdir(folder):
            for k in expected:
                if k.lower() in f.lower():
                    expected[k] = os.path.join(folder, f)
                    break
        
        mat = props.material
        if not mat or not mat.use_nodes:
            self.report({'ERROR'}, "No valid material selected.")
            return {'CANCELLED'}
        
        cnt = 0
        for node in mat.node_tree.nodes:
            if node.type=='TEX_IMAGE' and node.label in expected:
                fp = expected[node.label]
                if fp and os.path.exists(fp):
                    try:
                        node.image = bpy.data.images.load(fp, check_existing=True)
                        if node.label == 'Diffuse':
                             node.image.colorspace_settings.name = 'sRGB'
                        else:
                             node.image.colorspace_settings.name = 'Non-Color'
                        cnt += 1
                        if node.label == 'Diffuse':
                            props.bake_width, props.bake_height = node.image.size
                            self.report({'INFO'},f"Bake size updated: {props.bake_width}×{props.bake_height}")
                    except Exception as e:
                        self.report({'WARNING'},f"Failed load {fp}: {e}")
        
        self.report({'INFO'}, f"Swapped {cnt} textures.")
        return {'FINISHED'}


class HAIRCARD_OT_BakeTextures(bpy.types.Operator):
    bl_idname = "haircard.bake_textures"
    bl_label = "Bake Hair Card Maps"
    bl_description = "Bake maps to flat planes"
    bl_options = {'REGISTER'}

    _timer = None
    materials = None
    bake_sequence = None
    base_dir = None
    obj = None
    mesh_eval = None
    temp_obj = None
    scene = None
    step = 0
    total_steps = 0
    prev_engine = None

    def invoke(self, context, event):
        self.step = 0
        self.bake_phase = 'SETUP'
        self.current_setup = None

        props = context.scene.haircard_switcher
        w, h = props.bake_width, props.bake_height
        out = bpy.path.abspath(props.bake_path)
        self.obj = context.object

        if not (w and h) or not os.path.isdir(out) or not self.obj:
            self.report({'ERROR'}, "Bake prerequisites missing.")
            return {'CANCELLED'}

        deps = context.evaluated_depsgraph_get()
        eval_obj = self.obj.evaluated_get(deps)
        self.mesh_eval = bpy.data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=deps)
        self.temp_obj = bpy.data.objects.new(f"BakeObj_{self.obj.name}", self.mesh_eval)
        self.temp_obj.matrix_world = self.obj.matrix_world.copy()
        context.collection.objects.link(self.temp_obj)

        idx = self.mesh_eval.attributes.find('StoreUV')
        if idx != -1:
            self.mesh_eval.attributes.active_index = idx
            context.view_layer.objects.active = self.temp_obj
            bpy.ops.object.mode_set(mode='OBJECT')
            try: bpy.ops.geometry.attribute_convert(mode='GENERIC', domain='CORNER', data_type='FLOAT2')
            except: pass

        bpy.ops.object.select_all(action='DESELECT')
        self.temp_obj.select_set(True)
        context.view_layer.objects.active = self.temp_obj

        self.scene = context.scene
        self.prev_engine = self.scene.render.engine
        self.scene.render.engine = 'CYCLES'
        self.scene.cycles.samples = 16

        uv = self.mesh_eval.uv_layers.get('StoreUV')
        if uv: self.mesh_eval.uv_layers.active = uv

        self.base_dir = os.path.join(out, f"{self.obj.name}_textures")
        os.makedirs(self.base_dir, exist_ok=True)

        self.bake_sequence = [
            ('base_color', 'DIFFUSE', {'use_color': True}),
            ('roughness', 'ROUGHNESS', {}),
            ('specular', 'GLOSSY', {'use_color': True}),
            ('metallic', 'GLOSSY', {'use_color': True}),
            ('alpha', 'DIFFUSE', {'use_color': False}),
            ('normal', 'NORMAL', {'normal_space': 'TANGENT'})
        ]
        
        self.materials = list(self.temp_obj.data.materials)
        self.total_steps = len(self.materials) * len(self.bake_sequence)

        wm = context.window_manager
        wm.progress_begin(0, self.total_steps)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()
        self.scene.render.engine = self.prev_engine
        if self.temp_obj: bpy.data.objects.remove(self.temp_obj)
        if self.mesh_eval: bpy.data.meshes.remove(self.mesh_eval)
        context.scene.haircard_switcher.bake_progress = 0.0

    def _get_bsdf_socket(self, node, names):
        for name in names:
            if name in node.inputs: return node.inputs[name]
        return None

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            self._cleanup(context)
            self.report({'WARNING'}, "Bake cancelled.")
            return {'CANCELLED'}

        if event.type != 'TIMER': return {'PASS_THROUGH'}

        props = context.scene.haircard_switcher

        if self.bake_phase == 'SETUP':
            if self.step >= self.total_steps:
                self._cleanup(context)
                self.report({'INFO'}, f"Saved to {self.base_dir}")
                return {'FINISHED'}
            
            mat_index  = self.step // len(self.bake_sequence)
            pass_index = self.step % len(self.bake_sequence)
            map_name, bake_type, bake_kwargs = self.bake_sequence[pass_index]
            mat = self.materials[mat_index]
            
            if not mat or not mat.use_nodes:
                self.step += 1
                return {'RUNNING_MODAL'}

            self.temp_obj.active_material_index = mat_index
            self.temp_obj.active_material = mat
            nt = mat.node_tree

            img = bpy.data.images.new(f"{self.obj.name}_{mat.name}_{map_name}", props.bake_width, props.bake_height, alpha=True)
            bake_tex = nt.nodes.new('ShaderNodeTexImage')
            bake_tex.image = img
            bake_tex.select = True
            nt.nodes.active = bake_tex

            out_node = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
            source_socket = None
            emission = None
            
            for node in nt.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    if map_name == 'base_color': source_socket = node.inputs['Base Color']
                    elif map_name == 'alpha': source_socket = node.inputs['Alpha']
                    elif map_name == 'roughness': source_socket = node.inputs['Roughness']
                    elif map_name == 'specular': source_socket = self._get_bsdf_socket(node, ['Specular IOR Level', 'Specular'])
                    elif map_name == 'metallic': source_socket = node.inputs['Metallic']
                if map_name == 'normal' and node.type == 'NORMAL_MAP' and node.inputs['Color'].is_linked:
                    source_socket = node.inputs['Color']
                
                if source_socket and source_socket.is_linked:
                    source_socket = source_socket.links[0].from_socket
                    break
                else:
                    source_socket = None

            link_surface = None
            orig_link = None
            
            if out_node:
                emission = nt.nodes.new('ShaderNodeEmission')
                surf_input = out_node.inputs['Surface']
                if surf_input.is_linked:
                    orig_link = surf_input.links[0].from_socket
                    nt.links.remove(surf_input.links[0])
                link_surface = nt.links.new(emission.outputs['Emission'], surf_input)
                
                if source_socket: nt.links.new(source_socket, emission.inputs['Color'])
                else:
                    def_val = (0,0,0,1)
                    if map_name == 'roughness': def_val = (0.5, 0.5, 0.5, 1)
                    elif map_name == 'alpha': def_val = (1, 1, 1, 1)
                    elif map_name == 'normal': def_val = (0.5, 0.5, 1, 1)
                    emission.inputs['Color'].default_value = def_val

            self.current_setup = {
                'mat': mat, 'map_name': map_name, 'nt': nt, 'bake_tex': bake_tex, 'emission': emission,
                'img': img, 'link_surface': link_surface, 'orig_link': orig_link,
                'surf_input': surf_input if out_node else None,
            }
            self.bake_phase = 'BAKE'
            return {'RUNNING_MODAL'}

        elif self.bake_phase == 'BAKE':
            s = self.current_setup
            nt = s['nt']
            
            file_copied = False
            if s['map_name'] in {'normal', 'specular', 'metallic'}:
                src_path = None
                target_node_type = 'NORMAL_MAP' if s['map_name'] == 'normal' else 'BSDF_PRINCIPLED'
                for node in nt.nodes:
                    if node.type == target_node_type:
                        socket = None
                        if s['map_name'] == 'normal': socket = node.inputs['Color']
                        elif s['map_name'] == 'specular': socket = self._get_bsdf_socket(node, ['Specular IOR Level', 'Specular'])
                        elif s['map_name'] == 'metallic': socket = node.inputs['Metallic']
                        if socket and socket.is_linked:
                            link_node = socket.links[0].from_node
                            if link_node.type == 'TEX_IMAGE' and link_node.image:
                                src_path = bpy.path.abspath(link_node.image.filepath)
                        break

                if src_path and os.path.exists(src_path):
                    mat_dir = os.path.join(self.base_dir, s['mat'].name)
                    os.makedirs(mat_dir, exist_ok=True)
                    dst = os.path.join(mat_dir, f"{self.obj.name}_{s['mat'].name}_{s['map_name']}.png")
                    try:
                        shutil.copy(src_path, dst)
                        file_copied = True
                    except: pass

            if not file_copied:
                self.scene.render.bake.use_pass_direct = False
                self.scene.render.bake.use_pass_indirect = False
                self.scene.render.bake.use_pass_color = True
                bpy.ops.object.bake(type='EMIT')
                mat_dir = os.path.join(self.base_dir, s['mat'].name)
                os.makedirs(mat_dir, exist_ok=True)
                fp = os.path.join(mat_dir, f"{self.obj.name}_{s['mat'].name}_{s['map_name']}.png")
                use_cm = (s['map_name'] == 'base_color')
                with context.temp_override(edit_image=s['img']):
                    bpy.ops.image.save_as(save_as_render=False, filepath=fp, relative_path=False, show_multiview=False, use_color_management=use_cm, file_format='PNG')

            if s.get('link_surface'): nt.links.remove(s['link_surface'])
            if s.get('orig_link') and s.get('surf_input'):
                try: nt.links.new(s['orig_link'], s['surf_input'])
                except: pass
            if s.get('emission'): nt.nodes.remove(s['emission'])
            nt.nodes.remove(s['bake_tex'])
            bpy.data.images.remove(s['img'])

            self.step += 1
            context.window_manager.progress_update(self.step)
            props.bake_progress = self.step / max(self.total_steps, 1)
            self.bake_phase = 'SETUP'
            return {'RUNNING_MODAL'}

classes = (HairCardSwitcherProperties, HAIRCARD_PT_Switcher, HAIRCARD_OT_SwapTextures, HAIRCARD_OT_BakeTextures, StrandKitPreferences)

@persistent
def _strahkit_reset_progress(dummy):
    addon = bpy.context.preferences.addons.get(__package__)
    if addon: addon.preferences.asset_download_progress = 0.0

@persistent
def _strandkit_verify_on_load(dummy):
    if "StrandKit" in bpy.context.preferences.addons:
        from . import __init__
        try: __init__.verify_asset_library()
        except: pass

def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.haircard_switcher = PointerProperty(type=HairCardSwitcherProperties)
    try: addon_updater_ops.register(bl_info)
    except Exception as e: print(f"[StrandKit] Updater error: {e}")
    bpy.app.handlers.load_post.append(_strahkit_reset_progress)
    bpy.app.handlers.load_post.append(_strandkit_verify_on_load)

def unregister():
    if _strahkit_reset_progress in bpy.app.handlers.load_post: bpy.app.handlers.load_post.remove(_strahkit_reset_progress)
    if _strandkit_verify_on_load in bpy.app.handlers.load_post: bpy.app.handlers.load_post.remove(_strandkit_verify_on_load)
    addon_updater_ops.unregister()
    del bpy.types.Scene.haircard_switcher
    for c in reversed(classes): bpy.utils.unregister_class(c)

if __name__=="__main__": register()
