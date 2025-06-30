bl_info = {
    "name": "StrandKit - Hair Card Texture Switcher",
    "author": "Nino Defoq",
    "version": (1, 0, 9),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > StrandKit",
    "description": "Switches hair card textures based on folder structure and bakes maps with progress and cancel",
    "category": "Material",
}

import bpy
import os
import gpu
from gpu.types import GPUVertFormat, GPUVertBuf
from gpu.shader import from_builtin
from . import addon_updater_ops

class StrandKitPreferences(bpy.types.AddonPreferences):
    """Demo bare-bones preferences"""
    bl_idname = __package__

    # Addon updater preferences.

    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Updates",
        description="If enabled, checks for updates automatically at intervals.",
        default=True,
    )

    updater_interval_months: bpy.props.IntProperty(
        name='Months',
        description="Number of months between checking for updates",
        default=0,
        min=0)

    updater_interval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
        max=31)

    updater_interval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23)

    updater_interval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59)

    def draw(self, context):
        layout = self.layout

        # Works best if a column, or even just self.layout.
        mainrow = layout.row()
        col = mainrow.column()

        # Updater draw function, could also pass in col as third arg.
        addon_updater_ops.update_settings_ui(self, context)

        # Alternate draw function, which is more condensed and can be
        # placed within an existing draw function. Only contains:
        #   1) check for update/update now buttons
        #   2) toggle for auto-check (interval will be equal to what is set above)
        # addon_updater_ops.update_settings_ui_condensed(self, context, col)

        # Adding another column to help show the above condensed ui as one column
        # col = mainrow.column()
        # col.scale_y = 2
        # ops = col.operator("wm.url_open","Open webpage ")
        # ops.url=addon_updater_ops.updater.website

def list_dirs(path):
    try:
        return [d for d in sorted(os.listdir(path)) if os.path.isdir(os.path.join(path, d))]
    except:
        return []

class HairCardSwitcherProperties(bpy.types.PropertyGroup):
    material: bpy.props.PointerProperty(
        name="Material",
        type=bpy.types.Material,
        description="Select the material to update textures in"
    )
    base_path: bpy.props.StringProperty(
        name="Hair Card Folder",
        subtype='DIR_PATH'
    )
    bake_width: bpy.props.IntProperty(
        name="Bake Width",
        description="Width (px) for baking"
    )
    bake_height: bpy.props.IntProperty(
        name="Bake Height",
        description="Height (px) for baking"
    )
    bake_path: bpy.props.StringProperty(
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

    hair_type: bpy.props.EnumProperty(name="Hair Type", items=get_hair_types)
    color: bpy.props.EnumProperty(name="Color", items=get_colors)
    thickness: bpy.props.EnumProperty(name="Thickness", items=get_thicknesses)
    density: bpy.props.EnumProperty(name="Density", items=get_densities)

class HAIRCARD_PT_Switcher(bpy.types.Panel):
    bl_label = "Hair Card Switcher"
    bl_idname = "HAIRCARD_PT_switcher"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'StrandKit'

    def draw(self, context):
        layout = self.layout
        props = context.scene.haircard_switcher
        layout.prop(props, "base_path")
        if props.base_path:
            layout.prop(props, "hair_type")
            if props.hair_type != "NONE":
                layout.prop(props, "color")
                if props.color != "NONE":
                    layout.prop(props, "thickness")
                    if props.thickness != "NONE":
                        layout.prop(props, "density")
            layout.prop(props, "material")
            layout.operator("haircard.swap_textures")
            if props.bake_width and props.bake_height:
                row = layout.row()
                row.enabled = False
                row.prop(props, "bake_width")
                row.prop(props, "bake_height")
                layout.prop(props, "bake_path")
                layout.operator("haircard.bake_textures")

class HAIRCARD_OT_SwapTextures(bpy.types.Operator):
    bl_idname = "haircard.swap_textures"
    bl_label = "Swap Hair Card Textures"
    bl_description = "Swap textures based on selected folders and detect bake size"

    def execute(self, context):
        props = context.scene.haircard_switcher
        folder = os.path.join(bpy.path.abspath(props.base_path), props.hair_type, props.color, props.thickness, props.density)
        expected = {t:None for t in ["Diffuse","Roughness","Specular","Normal","Depth","Startmask"]}
        for k in expected:
            for f in os.listdir(folder):
                if k.lower() in f.lower():
                    expected[k] = os.path.join(folder,f)
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
                        node.image.colorspace_settings.name = 'sRGB' if node.label=='Diffuse' else 'Non-Color'
                        cnt += 1
                        if node.label=='Diffuse':
                            props.bake_width, props.bake_height = node.image.size
                            self.report({'INFO'},f"Bake size: {props.bake_width}×{props.bake_height}")
                    except Exception as e:
                        self.report({'WARNING'},f"Failed load {fp}: {e}")
                else:
                    self.report({'WARNING'},f"Missing texture {node.label}")
        self.report({'INFO'}, f"Swapped {cnt} textures.")
        return {'FINISHED'}

class HAIRCARD_OT_BakeTextures(bpy.types.Operator):
    bl_idname = "haircard.bake_textures"
    bl_label = "Bake Hair Card Maps"
    bl_description = "Bake base color, roughness, specular, and alpha for each material"
    bl_options = {'REGISTER'}

    _timer = None
    _handle = None
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

    def draw_callback(self):
        # draw overlay progress bar using current context
        region = bpy.context.region
        width = region.width
        pct = self.step / max(self.total_steps, 1)
        bar_w = width * 0.4
        bar_h = 20
        x = (width - bar_w) / 2
        y = 30
        # prepare GPU state
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        # background bar
        coords = ((x, y), (x+bar_w, y), (x+bar_w, y+bar_h), (x, y+bar_h))
        fmt = GPUVertFormat()
        pos_id = fmt.attr_add(id="pos", comp_type='F32', len=2)
        vbo = GPUVertBuf(fmt, len=4)
        vbo.attr_fill(id=pos_id, data=coords)
        shader = from_builtin('2D_UNIFORM_COLOR')
        shader.bind()
        shader.uniform_float("color", (0,0,0,0.5))
        batch = gpu.batch.batch_for_shader(shader, 'TRI_FAN', buf=vbo)
        batch.draw(shader)
        # fill bar
        fill_w = bar_w * pct
        coords2 = ((x, y), (x+fill_w, y), (x+fill_w, y+bar_h), (x, y+bar_h))
        vbo.attr_fill(id=pos_id, data=coords2)
        shader.uniform_float("color", (0.2,0.6,1.0,0.8))
        batch.draw(shader)
        # restore GPU state
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_restore()
        region = context.region
        width = region.width
        pct = self.step / max(self.total_steps, 1)
        bar_w = width * 0.4
        bar_h = 20
        x = (width - bar_w) / 2
        y = 30
        # prepare GPU state
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        # background bar
        coords = ((x, y), (x+bar_w, y), (x+bar_w, y+bar_h), (x, y+bar_h))
        fmt = GPUVertFormat()
        pos_id = fmt.attr_add(id="pos", comp_type='F32', len=2)
        vbo = GPUVertBuf(fmt, len=4)
        vbo.attr_fill(id=pos_id, data=coords)
        shader = from_builtin('2D_UNIFORM_COLOR')
        shader.bind()
        shader.uniform_float("color", (0, 0, 0, 0.5))
        batch = gpu.batch.batch_for_shader(shader, 'TRI_FAN', buf=vbo)
        batch.draw(shader)
        # fill bar
        fill_w = bar_w * pct
        coords2 = ((x, y), (x+fill_w, y), (x+fill_w, y+bar_h), (x, y+bar_h))
        vbo.attr_fill(id=pos_id, data=coords2)
        shader.uniform_float("color", (0.2, 0.6, 1.0, 0.8))
        batch.draw(shader)
        # restore GPU state
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_restore()
        # fill
        fill_w = bar_w * pct
        coords2 = ((x, y), (x+fill_w, y), (x+fill_w, y+bar_h), (x, y+bar_h))
        vbo.attr_fill(id=pos_id, data=coords2)
        shader.uniform_float("color", (0.2,0.6,1.0,0.8))
        batch.draw(shader)

    def invoke(self, context, event):
        props = context.scene.haircard_switcher
        w,h = props.bake_width, props.bake_height
        out = bpy.path.abspath(props.bake_path)
        self.obj = context.object
        if not (w and h) or not os.path.isdir(out) or not self.obj:
            self.report({'ERROR'},"Bake prerequisites missing."); return{'CANCELLED'}
        deps = context.evaluated_depsgraph_get()
        eval_obj = self.obj.evaluated_get(deps)
        self.mesh_eval = bpy.data.meshes.new_from_object(eval_obj,preserve_all_data_layers=True,depsgraph=deps)
        self.temp_obj = bpy.data.objects.new(f"BakeObj_{self.obj.name}",self.mesh_eval)
        context.collection.objects.link(self.temp_obj)
        idx = self.mesh_eval.attributes.find('StoreUV')
        if idx!=-1:
            self.mesh_eval.attributes.active_index=idx
            context.view_layer.objects.active=self.temp_obj
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.geometry.attribute_convert(mode='GENERIC',domain='CORNER',data_type='FLOAT2')
        bpy.ops.object.select_all(action='DESELECT')
        self.temp_obj.select_set(True); context.view_layer.objects.active=self.temp_obj
        self.scene = context.scene
        self.prev_engine = self.scene.render.engine
        self.scene.render.engine='CYCLES'
        self.scene.cycles.bake_samples=2
        uv= self.mesh_eval.uv_layers.get('StoreUV')
        if uv: self.mesh_eval.uv_layers.active=uv
        self.base_dir=os.path.join(out,f"{self.obj.name}_textures"); os.makedirs(self.base_dir,exist_ok=True)
        self.bake_sequence=[('base_color','DIFFUSE',{'use_direct':False,'use_indirect':False,'use_color':True}),
                             ('roughness','ROUGHNESS',{'use_direct':False,'use_indirect':False}),
                             ('specular','GLOSSY',{'use_direct':False,'use_indirect':False,'use_color':True}),
                             ('alpha','EMIT',{})]
        self.materials=list(self.temp_obj.data.materials)
        self.total_steps=len(self.materials)*len(self.bake_sequence)
        wm=context.window_manager; wm.progress_begin(0,self.total_steps)
        self._handle=bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (), 'WINDOW', 'POST_PIXEL')
        self._timer=wm.event_timer_add(0.1,window=context.window)
        wm.modal_handler_add(self)
        return{'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type=='ESC' and event.value=='PRESS':
            # unlink any leftover emission hack link
            if self.emitted_link:
                for mat in self.materials:
                    nt = mat.node_tree
                    try:
                        nt.links.remove(self.emitted_link)
                    except:
                        pass
                self.emitted_link = None
            # remove draw handler and timer
            bpy.types.SpaceView3D.draw_handler_remove(self._handle,'WINDOW')
            context.window_manager.event_timer_remove(self._timer)
            # restore engine and cleanup
            self.scene.render.engine = self.prev_engine
            bpy.data.objects.remove(self.temp_obj)
            bpy.data.meshes.remove(self.mesh_eval)
            self.report({'WARNING'},"Bake cancelled by user.")
            return{'CANCELLED'}
            bpy.types.SpaceView3D.draw_handler_remove(self._handle,'WINDOW')
            context.window_manager.event_timer_remove(self._timer)
            self.scene.render.engine=self.prev_engine
            bpy.data.objects.remove(self.temp_obj); bpy.data.meshes.remove(self.mesh_eval)
            self.report({'WARNING'},"Bake cancelled by user."); return{'CANCELLED'}
        if event.type=='TIMER':
            mat_index=self.step//len(self.bake_sequence)
            pass_index=self.step%len(self.bake_sequence)
            mat=self.materials[mat_index]
            name,btype,flags=self.bake_sequence[pass_index]
            self.temp_obj.active_material_index=mat_index
            self.temp_obj.active_material=mat
            nt=mat.node_tree
            bs=self.scene.render.bake
            bs.use_pass_direct=flags.get('use_direct',False)
            bs.use_pass_indirect=flags.get('use_indirect',False)
            bs.use_pass_color=flags.get('use_color',False)
            if not(bs.use_pass_direct or bs.use_pass_indirect or bs.use_pass_color): bs.use_pass_color=True
            diff_node=next((n for n in nt.nodes if n.type=='TEX_IMAGE' and n.label=='Diffuse' and n.image),None)
            lw,lh=(diff_node.image.size if diff_node else (self.scene.haircard_switcher.bake_width,self.scene.haircard_switcher.bake_height))
            img=bpy.data.images.new(f"{self.obj.name}_{mat.name}_{name}",lw,lh,alpha=True)
            bake_node=nt.nodes.new('ShaderNodeTexImage'); bake_node.image=img; bake_node.select=True; nt.nodes.active=bake_node
                        # Emission hack for alpha
            emitted_link = None
            if name == 'alpha':
                pnode = next((n for n in nt.nodes if n.type=='BSDF_PRINCIPLED'), None)
                if pnode and pnode.inputs['Alpha'].links:
                    from_socket = pnode.inputs['Alpha'].links[0].from_socket
                    emitted_link = nt.links.new(from_socket, pnode.inputs['Emission Strength'])

                # perform bake
                bpy.ops.object.bake(type=btype)
            mat_dir=os.path.join(self.base_dir,mat.name)
            fp=os.path.join(mat_dir,f"{self.obj.name}_{mat.name}_{name}.png")
            img.filepath_raw=fp; img.file_format='PNG'; img.save()
            try: nt.nodes.remove(bake_node)
            except: pass
            self.step+=1; context.window_manager.progress_update(self.step)
            if self.step>=self.total_steps:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle,'WINDOW')
                context.window_manager.event_timer_remove(self._timer)
                context.window_manager.progress_end()
                self.scene.render.engine=self.prev_engine
                bpy.data.objects.remove(self.temp_obj); bpy.data.meshes.remove(self.mesh_eval)
                self.report({'INFO'},f"Baked maps to {self.base_dir}")
                return{'FINISHED'}
        return{'PASS_THROUGH'}

classes=(HairCardSwitcherProperties,HAIRCARD_PT_Switcher,HAIRCARD_OT_SwapTextures,HAIRCARD_OT_BakeTextures, StrandKitPreferences)

def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.haircard_switcher=bpy.props.PointerProperty(type=HairCardSwitcherProperties)
    
    # Register addon updater operations
    try:
        addon_updater_ops.register(bl_info)
        print("[INFO] Addon updater operations registered successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to register addon updater operations: {e}")

def unregister():
    for c in reversed(classes): bpy.utils.unregister_class(c)
    del bpy.types.Scene.haircard_switcher
    
    # Unregister addon updater operations
    addon_updater_ops.unregister()

if __name__=="__main__": register()
