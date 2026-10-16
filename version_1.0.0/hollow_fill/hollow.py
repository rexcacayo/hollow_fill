# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vaciar una pieza dejando una pared fija y abrirle un agujero de llenado (y un respiradero)
para rellenarla después con resina epoxi, poliuretano o espuma.

La pared interior sale de un campo de distancias (Mesh to Volume → Volume to Mesh): la pared
mide lo mismo en toda la pieza y las zonas más finas que dos paredes se quedan macizas, sin
pliegues ni caras cruzadas. Solo se deja hueco lo que el agujero alcanza: cualquier otra burbuja
interior se queda maciza, para que no quede aire encerrado sin rellenar.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import common

ROLE_RESULT = 'vaciado_de'
MAX_INNER_FACES = 160_000          # pared interior: suficiente detalle sin cargar la memoria


def _volume_inner(context, src, t, voxel):
    """Superficie a `t` hacia dentro de `src` (malla en coordenadas de mundo). bmesh o None."""
    col = context.scene.collection
    vol = bpy.data.volumes.new('_hueco_vol')
    vo = bpy.data.objects.new('_hueco_vol', vol)
    me = bpy.data.meshes.new('_hueco_in')
    mo = bpy.data.objects.new('_hueco_in', me)
    col.objects.link(vo)
    col.objects.link(mo)
    try:
        m = vo.modifiers.new('m2v', 'MESH_TO_VOLUME')
        m.object = src
        m.resolution_mode = 'VOXEL_SIZE'
        m.voxel_size = voxel
        m.interior_band_width = 2.0 * t      # densidad 0 en la superficie → 1 a 2t de profundidad
        m.density = 1.0
        v = mo.modifiers.new('v2m', 'VOLUME_TO_MESH')
        v.object = vo
        v.threshold = 0.5                    # → la isosuperficie queda justo a t
        v.resolution_mode = 'VOXEL_SIZE'
        v.voxel_size = voxel
        v.adaptivity = 0.0
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        ev = mo.evaluated_get(graph)
        out = ev.to_mesh()
        try:
            if not len(out.polygons):
                return None
            bm = bmesh.new()
            bm.from_mesh(out)
        finally:
            ev.to_mesh_clear()
        return bm
    finally:
        bpy.data.objects.remove(mo, do_unlink=True)
        bpy.data.meshes.remove(me)
        bpy.data.objects.remove(vo, do_unlink=True)
        bpy.data.volumes.remove(vol)


def _islands(bm):
    """Listas de caras conectadas."""
    bm.faces.ensure_lookup_table()
    seen, out = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            isl.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        out.append(isl)
    return out


def _island_volume(faces):
    vol = 0.0
    for f in faces:
        vs = [v.co for v in f.verts]
        for i in range(1, len(vs) - 1):
            vol += vs[0].dot(vs[i].cross(vs[i + 1])) / 6.0
    return abs(vol)


def _keep_faces(bm, keep):
    keep = {f.index for f in keep}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context='FACES')
    bm.faces.index_update()


def _bmesh_area(bm):
    return sum(f.calc_area() for f in bm.faces)


def _hole_from_point(outer_tree, inner_tree, p, n, t):
    """Agujero que entra por `p` (sobre la pieza, normal hacia fuera `n`) hasta el hueco.
    Devuelve (punto fuera, punto dentro del hueco) o None si debajo no hay hueco."""
    n = Vector(n).normalized()
    start = Vector(p) - n * (t * 0.02)
    hit_in = inner_tree.ray_cast(start, -n)
    hit_out = outer_tree.ray_cast(start - n * (t * 0.02), -n)       # por dónde sale al otro lado
    if hit_in[0] is None:
        return None
    if hit_out[0] is not None and hit_out[3] < hit_in[3]:
        return None
    return Vector(p), hit_in[0]


def _hole_from_cavity(outer_tree, q, direction):
    """Agujero desde un punto del hueco `q` hacia fuera siguiendo `direction` (o al punto más cercano)."""
    if direction is not None:
        hit = outer_tree.ray_cast(Vector(q), Vector(direction))
        if hit[0] is not None:
            return hit[0], Vector(q)
    loc, _n, _i, _d = outer_tree.find_nearest(Vector(q))
    return (loc, Vector(q)) if loc is not None else None


def _cutter_bmesh(holes, t):
    """Un cilindro por agujero, de fuera (sobresale) hasta dentro del hueco."""
    bm = bmesh.new()
    for out_p, in_p, radius in holes:
        axis = out_p - in_p
        L = axis.length
        if L < 1e-9:
            continue
        axis.normalize()
        a = in_p - axis * min(t * 0.5, radius)        # entra un poco en el hueco
        b = out_p + axis * max(t, radius)              # y sobresale por fuera
        c = common.cylinder_bmesh((a + b) / 2, axis, radius, (b - a).length, segments=48)
        me = bpy.data.meshes.new('_tmp')
        c.to_mesh(me)
        c.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    return bm


def hollow(context, obj, wall_mm=2.0, hole_mm=8.0, where='BOTTOM', point=None, normal=None,
           vent=True, vent_mm=3.0, density=1.1, unit='AUTO'):
    """Crea «<pieza>_vacio» (la pieza no se toca, se oculta). Devuelve el mensaje para el usuario.
    `where`: BOTTOM / TOP / POINT (punto y normal en coordenadas de mundo, unidades de Blender)."""
    if obj is None or obj.type != 'MESH':
        raise common.AddonError('Selecciona la pieza (una malla) que quieres vaciar.')
    code, f = common.resolve_unit(context.scene, unit, obj)
    t = wall_mm / f
    outer = common.world_bmesh(context, obj)
    try:
        if not outer.faces or any(not e.is_manifold for e in outer.edges):
            raise common.AddonError('La pieza tiene agujeros o caras sueltas. Pásala antes por «Dejar listo» '
                                    '(Print Ready) o Mesh Doctor y vuelve a vaciarla.')
        before = abs(outer.calc_volume(signed=True))
        dims = Vector(obj.dimensions)
        if min(dims) < 2.2 * t:
            raise common.AddonError(f'La pieza mide {min(dims) * f:.1f} mm en su parte más fina: con pared de '
                                    f'{wall_mm:g} mm no queda hueco. Baja la pared.')
        area = _bmesh_area(outer)
        voxel = min(max(t / 4.0, math.sqrt(area / MAX_INNER_FACES)), t / 1.5)
        # la malla de trabajo, en mundo, para que el volumen salga donde está la pieza
        src_me = bpy.data.meshes.new('_hueco_src')
        outer.to_mesh(src_me)
        src = bpy.data.objects.new('_hueco_src', src_me)
        context.scene.collection.objects.link(src)
        try:
            inner = _volume_inner(context, src, t, voxel)
        finally:
            bpy.data.objects.remove(src, do_unlink=True)
            bpy.data.meshes.remove(src_me)
        if inner is None:
            raise common.AddonError(f'La pieza es demasiado fina para vaciarla con pared de {wall_mm:g} mm. '
                                    'Baja la pared.')
        try:
            return _finish(context, obj, outer, inner, before, t, f, wall_mm, hole_mm, where, point, normal,
                           vent, vent_mm, density, code)
        finally:
            inner.free()
    finally:
        outer.free()


def _finish(context, obj, outer, inner, before, t, f, wall_mm, hole_mm, where, point, normal,
            vent, vent_mm, density, code):
    outer_tree = BVHTree.FromBMesh(outer)
    min_vol = (2.0 * t) ** 3                  # burbujas más pequeñas no merecen la pena
    islands = [isl for isl in _islands(inner) if _island_volume(isl) > min_vol]
    if not islands:
        raise common.AddonError(f'La pieza es demasiado fina para vaciarla con pared de {wall_mm:g} mm. Baja la pared.')
    r = hole_mm / f / 2.0
    # 1 · agujero de llenado y el hueco al que llega
    hole = None
    if where == 'POINT':
        if point is None:
            raise common.AddonError('Marca dónde va el agujero.')
        p = Vector(point)
        nn = Vector(normal) if normal is not None else None
        if nn is None or nn.length < 1e-9:
            loc, nn, _i, _d = outer_tree.find_nearest(p)
            p = loc
        _keep_faces(inner, [g for isl in islands for g in isl])
        inner_tree = BVHTree.FromBMesh(inner)
        hole = _hole_from_point(outer_tree, inner_tree, p, nn, t)
        if hole is None:
            raise common.AddonError('Ahí debajo la pieza es maciza (más fina que dos paredes). '
                                    'Marca el agujero en una zona más gruesa.')
        inner.faces.ensure_lookup_table()
        islands = _islands(inner)
        target = min(islands, key=lambda isl: min((v.co - hole[1]).length for g in isl for v in g.verts))
    else:
        target = max(islands, key=_island_volume)
        verts = {v for g in target for v in g.verts}
        sign = -1 if where == 'BOTTOM' else 1
        zs = np.array([v.co.z for v in verts])
        lim = zs.min() + t * 0.5 if sign < 0 else zs.max() - t * 0.5
        low = [v for v in verts if (v.co.z <= lim if sign < 0 else v.co.z >= lim)]
        mid = sum((v.co for v in low), Vector()) / len(low)      # en una cara plana: el centro, no una esquina
        q = min(low, key=lambda v: (v.co.xy - mid.xy).length).co.copy()
        hole = _hole_from_cavity(outer_tree, q, Vector((0, 0, sign)))
        if hole is None:
            raise common.AddonError('No encontré por dónde abrir el agujero. Prueba a marcarlo con clic.')
    dropped = len(islands) - 1
    _keep_faces(inner, target)
    cavity = _island_volume(inner.faces)
    holes = [(hole[0], hole[1], r)]
    # 2 · respiradero: en el punto del hueco más alejado del agujero (allí se queda el aire)
    vent_note = ''
    if vent:
        far = max(inner.verts, key=lambda v: (v.co - hole[1]).length).co.copy()
        if (far - hole[1]).length > 4.0 * hole_mm / f:
            v = _hole_from_cavity(outer_tree, far, None)
            if v is not None:
                holes.append((v[0], v[1], vent_mm / f / 2.0))
                vent_note = f' + respiradero Ø{vent_mm:g} mm'
    # 3 · cáscara = fuera + dentro dado la vuelta, y los agujeros
    bmesh.ops.reverse_faces(inner, faces=inner.faces[:])
    shell = outer.copy()
    me = bpy.data.meshes.new('_tmp')
    inner.to_mesh(me)
    shell.from_mesh(me)
    bpy.data.meshes.remove(me)
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    res = common.new_object(shell, f'{obj.name}_vacio', col, source=obj)
    shell.free()
    res[common.UNIT_PROP] = code
    res[ROLE_RESULT] = obj.name
    cut_bm = _cutter_bmesh(holes, t)
    cutter = common.new_object(cut_bm, '_agujeros', col)
    cut_bm.free()
    try:
        common.boolean(context, res, cutter, 'DIFFERENCE')
    except common.AddonError:
        common.remove_objects([res])
        raise common.AddonError('No pude abrir el agujero en ese sitio. Prueba otro punto o un diámetro menor.')
    finally:
        common.remove_objects([cutter])
    _closed, plastic = common.solid_info(res)
    ml = cavity * f ** 3 / 1000.0
    res['hueco_ml'] = round(ml, 1)
    obj.hide_set(True)
    for o in context.selected_objects:
        o.select_set(False)
    res.select_set(True)
    context.view_layer.objects.active = res
    where_txt = {'BOTTOM': 'abajo', 'TOP': 'arriba'}.get(where, 'donde marcaste')
    msg = (f'Vacía con pared de {wall_mm:g} mm. Hueco: {ml:.0f} ml (≈ {ml * density:.0f} g de relleno). '
           f'Plástico: {plastic * f ** 3 / 1000:.0f} ml de {before * f ** 3 / 1000:.0f}. '
           f'Agujero Ø{hole_mm:g} mm {where_txt}{vent_note}.')
    if dropped:
        msg += (f' {dropped} hueco{"s" if dropped > 1 else ""} que no conecta{"n" if dropped > 1 else ""} con el agujero '
                f'se deja{"n" if dropped > 1 else ""} macizo{"s" if dropped > 1 else ""}.')
    return msg
