# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {'name': 'Hollow Fill', 'author': 'Ricardo Lugaresi', 'version': (1, 0, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Hollow Fill',
           'description': 'Vacía la pieza con pared fija y le abre agujero de llenado y respiradero para '
                          'rellenarla con epoxi o poliuretano. Todo en modo Objeto',
           'category': 'Object'}

import bpy

from . import common, hollow

WHERE_ITEMS = [('CLICK', 'Con clic', 'Marcas con el ratón dónde va el agujero'),
               ('BOTTOM', 'Abajo', 'En el punto más bajo del hueco (le das la vuelta para rellenar)'),
               ('TOP', 'Arriba', 'En el punto más alto del hueco')]


class HollowProps(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades', items=common.UNIT_ITEMS, default='AUTO')
    wall: bpy.props.FloatProperty(name='Pared (mm)', default=2.0, min=0.8, max=20, precision=1,
                                  description='Grosor de la cáscara impresa')
    where: bpy.props.EnumProperty(name='Agujero', items=WHERE_ITEMS, default='CLICK')
    hole: bpy.props.FloatProperty(name='Agujero Ø (mm)', default=8.0, min=2, max=40, precision=1,
                                  description='Por aquí entra el relleno')
    vent: bpy.props.BoolProperty(name='Respiradero', default=True,
                                 description='Agujero pequeño en la punta más lejana del hueco para que salga el aire')
    vent_d: bpy.props.FloatProperty(name='Respiradero Ø (mm)', default=3.0, min=1, max=15, precision=1)
    density: bpy.props.FloatProperty(name='Densidad del relleno (g/ml)', default=1.1, min=0.02, max=3, precision=2,
                                     description='Epoxi ≈ 1,1 · poliuretano colado ≈ 1,1 · espuma ≈ 0,05-0,2')
    show_fine: bpy.props.BoolProperty(name='Ajustes', default=False)
    done: bpy.props.StringProperty(default='')
    export_folder: bpy.props.StringProperty(name='Carpeta', default='//Vaciados', subtype='DIR_PATH')
    scope: bpy.props.EnumProperty(name='Exportar', items=common.SCOPE_ITEMS, default='SELECTED')


def _model(context):
    for obj in [context.active_object] + list(context.selected_objects):
        if obj is not None and obj.type == 'MESH' and not common.is_helper(obj) and not obj.get(hollow.ROLE_RESULT):
            return obj
    return None


def _run(op, context, where, point=None, normal=None):
    p = context.scene.hollow_props
    try:
        msg = hollow.hollow(context, _model(context), p.wall, p.hole, where, point, normal,
                            p.vent, p.vent_d, p.density, p.model_unit)
    except common.AddonError as exc:
        op.report({'ERROR'}, str(exc))
        return {'CANCELLED'}
    p.done = msg
    op.report({'INFO'}, msg + ' Ctrl+Z para probar otros ajustes.')
    return {'FINISHED'}


class OBJECT_OT_hollow_fill(bpy.types.Operator):
    """Vacía la pieza seleccionada (la original no se toca)"""
    bl_idname = 'object.hollow_fill'; bl_label = 'Vaciar'; bl_options = {'REGISTER', 'UNDO'}
    where: bpy.props.EnumProperty(items=WHERE_ITEMS[1:] + [('POINT', 'Punto', '')], default='BOTTOM', options={'SKIP_SAVE'})
    point: bpy.props.FloatVectorProperty(size=3, options={'SKIP_SAVE'})
    normal: bpy.props.FloatVectorProperty(size=3, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        if self.where == 'POINT':
            return _run(self, context, 'POINT', tuple(self.point), tuple(self.normal))
        return _run(self, context, self.where)


class OBJECT_OT_hollow_fill_click(common.ClickPlacer, bpy.types.Operator):
    """Pasa el ratón por la pieza y haz clic donde quieres el agujero de llenado"""
    bl_idname = 'object.hollow_fill_click'; bl_label = 'Vaciar: marcar agujero'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic donde va el agujero de llenado · botón central gira la vista · Esc cancela'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def create_helper(self, context, model):
        p = context.scene.hollow_props
        f = common.factor(context.scene, p.model_unit, model)
        r = p.hole / f / 2
        col = model.users_collection[0] if model.users_collection else context.scene.collection
        h = common.cylinder('Agujero_llenado', (0, 0, 0), (0, 0, 1), r, max(r, p.wall / f) * 2, col)
        h.display_type = 'WIRE'
        h[common.ROLE] = common.ROLE_CUTTER
        return h

    def place(self, context, helper, loc, normal):
        common.place_cutter(helper, loc, normal)
        self._hit = (tuple(loc), tuple(normal))

    def commit(self, context, model, helper):
        common.remove_objects([helper])
        for o in context.selected_objects:
            o.select_set(False)
        model.select_set(True)
        context.view_layer.objects.active = model
        p = context.scene.hollow_props
        msg = hollow.hollow(context, model, p.wall, p.hole, 'POINT', self._hit[0], self._hit[1],
                            p.vent, p.vent_d, p.density, p.model_unit)
        p.done = msg
        return msg


class OBJECT_OT_hollow_export(bpy.types.Operator):
    """Exporta a STL en milímetros"""
    bl_idname = 'object.hollow_export'; bl_label = 'Exportar STL'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.hollow_props
        try:
            files = common.export_meshes(context, p.export_folder, p.scope, p.model_unit)
        except (common.AddonError, OSError) as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        where = files[0].parent if files else common.export_folder(p.export_folder)
        self.report({'INFO'}, f'{len(files)} STL exportados en mm en {where}'); return {'FINISHED'}


def _wrap(layout, text, width=38):
    col = layout.column(align=True); col.scale_y = .8
    line = ''
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            col.label(text=line); line = word
        else:
            line = (line + ' ' + word).strip()
    if line:
        col.label(text=line)


class VIEW3D_PT_hollow(bpy.types.Panel):
    bl_label = 'Hollow Fill'; bl_idname = 'VIEW3D_PT_hollow'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Hollow Fill'

    def draw(self, context):
        layout = self.layout; p = context.scene.hollow_props
        layout.use_property_split = True; layout.use_property_decorate = False
        if common.draw_mode_warning(layout, context):
            return
        box = layout.box()
        box.label(text='1 · Pieza', icon='MESH_DATA')
        model = _model(context)
        if model is None:
            row = box.row(); row.alert = True
            row.label(text='Selecciona la pieza', icon='ERROR')
        else:
            mm = common.factor(context.scene, p.model_unit, model)
            d = [x * mm for x in model.dimensions]
            box.label(text=model.name, icon='OBJECT_DATA')
            box.label(text=f'{d[0]:.0f} × {d[1]:.0f} × {d[2]:.0f} mm')
        box = layout.box()
        box.label(text='2 · Pared y agujero', icon='MOD_SOLIDIFY')
        box.prop(p, 'wall')
        box.prop(p, 'hole')
        row = box.row(); row.use_property_split = False
        row.prop(p, 'where', expand=True)
        box.prop(p, 'vent')
        fine = box.column()
        fine.prop(p, 'show_fine', icon='TRIA_DOWN' if p.show_fine else 'TRIA_RIGHT', emboss=False)
        if p.show_fine:
            fine.prop(p, 'vent_d')
            fine.prop(p, 'density')
            fine.prop(p, 'model_unit')
        col = layout.column(); col.scale_y = 1.6
        if p.where == 'CLICK':
            col.operator('object.hollow_fill_click', text='Vaciar · marcar agujero', icon='RESTRICT_SELECT_OFF')
        else:
            col.operator('object.hollow_fill', text='Vaciar', icon='MOD_SOLIDIFY').where = p.where
        if p.done:
            _wrap(layout, p.done)
        box = layout.box()
        box.label(text='3 · Exportar STL', icon='EXPORT')
        row = box.row(); row.use_property_split = False
        row.prop(p, 'scope', expand=True)
        box.prop(p, 'export_folder')
        box.operator('object.hollow_export', icon='EXPORT')


classes = (HollowProps, OBJECT_OT_hollow_fill, OBJECT_OT_hollow_fill_click, OBJECT_OT_hollow_export, VIEW3D_PT_hollow)


def register():
    common.register_classes(classes, 'hollow_props', HollowProps)


def unregister():
    common.unregister_classes(classes, 'hollow_props')
