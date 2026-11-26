import bpy, bmesh, math, os, random, sys
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.environ.get('Q', 'preview')
OUT = os.environ.get('OUT', os.path.join(HERE, 'vault_%s.png' % Q))
random.seed(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
C = bpy.context

def active():
    return C.view_layer.objects.active

def select_only(o):
    for x in C.view_layer.objects:
        x.select_set(False)
    o.select_set(True)
    C.view_layer.objects.active = o

def smooth(o, angle=35):
    select_only(o)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))
    except Exception:
        bpy.ops.object.shade_smooth()

def bevel(o, w=0.01, seg=3, angle=40):
    m = o.modifiers.new('bev', 'BEVEL')
    m.width = w; m.segments = seg
    m.limit_method = 'ANGLE'; m.angle_limit = math.radians(angle)
    return m

def cyl(r, depth, loc, rot=(0, 0, 0), verts=96, name='cyl'):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = active(); o.name = name; return o

def cube(size, loc, rot=(0, 0, 0), name='cube'):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = active(); o.scale = size; o.name = name
    select_only(o); bpy.ops.object.transform_apply(scale=True)
    return o

def sphere(r, loc, seg=24, name='sph'):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, radius=r, location=loc)
    o = active(); o.name = name; return o

def torus(R, r, loc, rot=(0, 0, 0), name='tor'):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, major_segments=128, minor_segments=24, location=loc, rotation=rot)
    o = active(); o.name = name; return o

def boolean_diff(a, b):
    m = a.modifiers.new('bool', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = b; m.solver = 'EXACT'
    select_only(a); bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(b, do_unlink=True)

def parent(child, par):
    child.parent = par
    child.matrix_parent_inverse = par.matrix_world.inverted()

def setmat(o, m):
    o.data.materials.clear(); o.data.materials.append(m)

# ---------------- materiais ----------------
def new_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; p = nt.nodes.get('Principled BSDF')
    return m, nt, p

def inp(p, *names):
    for n in names:
        if n in p.inputs: return p.inputs[n]
    return None

def noise_rough(nt, p, scale, lo, hi, detail=6):
    tc = nt.nodes.new('ShaderNodeTexCoord')
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = scale; nz.inputs['Detail'].default_value = detail
    nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    mr = nt.nodes.new('ShaderNodeMapRange'); mr.inputs['To Min'].default_value = lo; mr.inputs['To Max'].default_value = hi
    mr.inputs['From Min'].default_value = 0.3; mr.inputs['From Max'].default_value = 0.7
    nt.links.new(nz.outputs['Fac'], mr.inputs['Value']); nt.links.new(mr.outputs['Result'], p.inputs['Roughness'])
    return tc

def add_bump(nt, p, scale, strength, tc=None):
    if tc is None:
        tc = nt.nodes.new('ShaderNodeTexCoord')
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = scale; nz.inputs['Detail'].default_value = 8
    nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    b = nt.nodes.new('ShaderNodeBump'); b.inputs['Strength'].default_value = strength; b.inputs['Distance'].default_value = 0.002
    nt.links.new(nz.outputs['Fac'], b.inputs['Height']); nt.links.new(b.outputs['Normal'], p.inputs['Normal'])

def metal(name, col, rough=(0.2, 0.35), aniso=0.0, radial=False, bump=0.0):
    m, nt, p = new_mat(name)
    p.inputs['Base Color'].default_value = (*col, 1); p.inputs['Metallic'].default_value = 1.0
    tc = noise_rough(nt, p, 18, rough[0], rough[1])
    a = inp(p, 'Anisotropic')
    if a is not None and aniso > 0:
        a.default_value = aniso
        if radial:
            t = nt.nodes.new('ShaderNodeTangent'); t.direction_type = 'RADIAL'; t.axis = 'Y'
            nt.links.new(t.outputs['Tangent'], p.inputs['Tangent'])
    if bump > 0: add_bump(nt, p, 260, bump, tc)
    return m

def dielectric(name, cols, rough=(0.8, 0.95), scale=4, bump=0.15, bscale=80):
    m, nt, p = new_mat(name)
    tc = nt.nodes.new('ShaderNodeTexCoord')
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = scale; nz.inputs['Detail'].default_value = 10
    nt.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (*cols[0], 1); ramp.color_ramp.elements[1].color = (*cols[1], 1)
    ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[1].position = 0.65
    nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], p.inputs['Base Color'])
    mr = nt.nodes.new('ShaderNodeMapRange'); mr.inputs['To Min'].default_value = rough[0]; mr.inputs['To Max'].default_value = rough[1]
    nt.links.new(nz.outputs['Fac'], mr.inputs['Value']); nt.links.new(mr.outputs['Result'], p.inputs['Roughness'])
    if bump > 0: add_bump(nt, p, bscale, bump, tc)
    return m


def mix_rgba(nt):
    m = nt.nodes.new('ShaderNodeMix'); m.data_type = 'RGBA'
    A = [x for x in m.inputs if x.name == 'A' and x.type == 'RGBA'][0]
    B = [x for x in m.inputs if x.name == 'B' and x.type == 'RGBA'][0]
    F = [x for x in m.inputs if x.name == 'Factor' and x.type == 'VALUE'][0]
    O = [x for x in m.outputs if x.type == 'RGBA'][0]
    return m, F, A, B, O

def image_mat(name, path, rough=0.5, metallic=0.0, alpha_to=None):
    m, nt, p = new_mat(name)
    img = bpy.data.images.load(path)
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Cubic'; tex.extension = 'CLIP'
    p.inputs['Roughness'].default_value = rough; p.inputs['Metallic'].default_value = metallic
    if alpha_to is not None:
        mix, F, A, B, O = mix_rgba(nt)
        A.default_value = (*alpha_to, 1)
        nt.links.new(tex.outputs['Alpha'], F); nt.links.new(tex.outputs['Color'], B)
        nt.links.new(O, p.inputs['Base Color'])
    else:
        nt.links.new(tex.outputs['Color'], p.inputs['Base Color'])
    return m

M_steel = metal('aco_escovado', (0.60, 0.60, 0.61), (0.25, 0.3), aniso=0.6, radial=True, bump=0.008)
M_steel_dark = metal('aco_escuro', (0.30, 0.30, 0.31), (0.3, 0.36), aniso=0.3, bump=0.008)
M_chrome = metal('cromado', (0.86, 0.86, 0.87), (0.05, 0.12))
M_stainless = metal('inox', (0.66, 0.66, 0.66), (0.2, 0.26), aniso=0.5, bump=0.005)
M_brass = metal('latao', (0.80, 0.58, 0.30), (0.22, 0.35))
M_gold = metal('ouro', (1.0, 0.71, 0.29), (0.12, 0.2))
M_box = metal('gavetas', (0.55, 0.52, 0.47), (0.3, 0.36), aniso=0.4, bump=0.006)

def concrete_panels():
    # concreto aparente: manchas, juntas entre placas (2,4 x 1,2 m) e furos de forma
    m, nt, p = new_mat('concreto')
    N = nt.nodes; L = nt.links.new
    def mth(op, a, b=None, clamp=False):
        n = N.new('ShaderNodeMath'); n.operation = op; n.use_clamp = clamp
        for k, v in enumerate((a, b)):
            if v is None: continue
            if isinstance(v, (int, float)): n.inputs[k].default_value = v
            else: L(v, n.inputs[k])
        return n.outputs[0]
    def smooth(v, a, b, inv=False):
        n = N.new('ShaderNodeMapRange'); n.interpolation_type = 'SMOOTHSTEP'
        n.inputs['From Min'].default_value = a; n.inputs['From Max'].default_value = b
        n.inputs['To Min'].default_value = 1.0 if inv else 0.0; n.inputs['To Max'].default_value = 0.0 if inv else 1.0
        L(v, n.inputs['Value']); return n.outputs['Result']
    tc = N.new('ShaderNodeTexCoord'); sx = N.new('ShaderNodeSeparateXYZ'); L(tc.outputs['Object'], sx.inputs['Vector'])
    X, Z = sx.outputs['X'], sx.outputs['Z']
    def joint(c, size, w):
        f = mth('FRACT', mth('ADD', mth('DIVIDE', c, size), 0.5))
        d = mth('MULTIPLY', mth('ABSOLUTE', mth('SUBTRACT', f, 0.5)), size)
        return smooth(d, w * 0.4, w, inv=True)
    jx = joint(X, 2.4, 0.007); jz = joint(Z, 1.2, 0.007)
    J = mth('MAXIMUM', jx, jz)
    def cell(c, size, off):
        f = mth('FRACT', mth('ADD', mth('DIVIDE', c, size), off))
        return mth('MULTIPLY', mth('SUBTRACT', f, 0.5), size)
    hx = cell(X, 0.6, 0.0); hz = cell(Z, 0.6, 0.0)
    cmb = N.new('ShaderNodeCombineXYZ'); L(hx, cmb.inputs['X']); L(hz, cmb.inputs['Y'])
    ln = N.new('ShaderNodeVectorMath'); ln.operation = 'LENGTH'; L(cmb.outputs['Vector'], ln.inputs[0])
    H = smooth(ln.outputs['Value'], 0.011, 0.016, inv=True)
    nz = N.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 2.5; nz.inputs['Detail'].default_value = 10; L(tc.outputs['Object'], nz.inputs['Vector'])
    nz2 = N.new('ShaderNodeTexNoise'); nz2.inputs['Scale'].default_value = 40; nz2.inputs['Detail'].default_value = 6; L(tc.outputs['Object'], nz2.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.19, 0.19, 0.195, 1); ramp.color_ramp.elements[1].color = (0.29, 0.29, 0.295, 1)
    ramp.color_ramp.elements[0].position = 0.3; ramp.color_ramp.elements[1].position = 0.7
    L(nz.outputs['Fac'], ramp.inputs['Fac'])
    dark = mth('MULTIPLY', mth('MAXIMUM', J, H), 0.65)
    mixc, F, A, B, O = mix_rgba(nt); L(dark, F); L(ramp.outputs['Color'], A); B.default_value = (0.05, 0.05, 0.052, 1)
    L(O, p.inputs['Base Color'])
    rr = N.new('ShaderNodeMapRange'); rr.inputs['To Min'].default_value = 0.78; rr.inputs['To Max'].default_value = 0.95; L(nz2.outputs['Fac'], rr.inputs['Value']); L(rr.outputs['Result'], p.inputs['Roughness'])
    h = mth('SUBTRACT', mth('MULTIPLY', nz2.outputs['Fac'], 0.25), mth('MAXIMUM', J, H))
    bump = N.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.6; bump.inputs['Distance'].default_value = 0.004
    L(h, bump.inputs['Height']); L(bump.outputs['Normal'], p.inputs['Normal'])
    return m

M_wall = concrete_panels()
M_floor = dielectric('piso', [(0.11, 0.11, 0.115), (0.17, 0.17, 0.175)], (0.18, 0.4), 2.5, 0.05, 40)
M_ceiling = dielectric('teto', [(0.32, 0.32, 0.32), (0.4, 0.4, 0.4)], (0.85, 0.95), 3, 0.1)
M_keyhole = metal('fechadura', (0.08, 0.08, 0.08), (0.3, 0.4))
M_band = dielectric('cinta', [(0.80, 0.72, 0.55), (0.86, 0.79, 0.62)], (0.6, 0.7), 30, 0.0)
M_logo = image_mat('placa_logo', os.path.join(HERE, 'logo.png'), rough=0.35, metallic=0.0, alpha_to=(0.33, 0.33, 0.34))

# cédula: imagem na face de cima/baixo, borda de papel empilhado nas laterais
M_cash, nt, p = new_mat('cedulas')
img = bpy.data.images.load(os.path.join(HERE, 'cash.png'))
tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Cubic'
geo = nt.nodes.new('ShaderNodeNewGeometry')
sep = nt.nodes.new('ShaderNodeSeparateXYZ'); nt.links.new(geo.outputs['True Normal'], sep.inputs['Vector'])
absn = nt.nodes.new('ShaderNodeMath'); absn.operation = 'ABSOLUTE'; nt.links.new(sep.outputs['Z'], absn.inputs[0])
gt = nt.nodes.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'; gt.inputs[1].default_value = 0.5; nt.links.new(absn.outputs[0], gt.inputs[0])
wave = nt.nodes.new('ShaderNodeTexWave'); wave.wave_type = 'BANDS'; wave.bands_direction = 'Z'; wave.inputs['Scale'].default_value = 900
wave.inputs['Distortion'].default_value = 2
nt.links.new(geo.outputs['Position'], wave.inputs['Vector'])
er = nt.nodes.new('ShaderNodeValToRGB'); er.color_ramp.elements[0].color = (0.55, 0.62, 0.50, 1); er.color_ramp.elements[1].color = (0.80, 0.84, 0.74, 1)
nt.links.new(wave.outputs['Fac'], er.inputs['Fac'])
mix, F, A, B, O = mix_rgba(nt)
nt.links.new(gt.outputs[0], F); nt.links.new(er.outputs['Color'], A); nt.links.new(tex.outputs['Color'], B)
hs = nt.nodes.new('ShaderNodeHueSaturation'); hs.inputs['Saturation'].default_value = 1.5; hs.inputs['Value'].default_value = 0.72
nt.links.new(O, hs.inputs['Color']); nt.links.new(hs.outputs['Color'], p.inputs['Base Color']); p.inputs['Roughness'].default_value = 0.75

# ---------------- cena ----------------
CZ = 1.3       # altura do centro da porta
R = 1.1        # raio da porta

floor = cube((30, 20, 0.1), (0, -2.0, -0.05), name='piso'); setmat(floor, M_floor)

wall = cube((26, 0.7, 6), (0, 0.35, 3.0), name='parede')
boolean_diff(wall, cyl(1.36, 2, (0, 0.35, CZ), (math.pi / 2, 0, 0), 128))
bevel(wall, 0.015, 2); setmat(wall, M_wall)

ring = cyl(1.42, 0.82, (0, 0.29, CZ), (math.pi / 2, 0, 0), 160, 'aro')
boolean_diff(ring, cyl(1.13, 2, (0, 0.29, CZ), (math.pi / 2, 0, 0), 160))
bevel(ring, 0.02, 4); setmat(ring, M_steel_dark); smooth(ring)
for i in range(28):
    a = i / 28 * math.tau
    b = cyl(0.03, 0.03, (math.cos(a) * 1.29, -0.13, CZ + math.sin(a) * 1.29), (math.pi / 2, 0, 0), 6, 'parafuso')
    bevel(b, 0.004, 2); setmat(b, M_chrome)

# sala interna
room_floor = cube((4.9, 4.4, 0.02), (0, 2.85, 0.005), name='piso_sala'); setmat(room_floor, M_floor)
ceil = cube((4.9, 4.4, 0.1), (0, 2.85, 3.25), name='teto'); setmat(ceil, M_ceiling)

def box_unit(name):
    parts = []
    b = cube((0.255, 0.05, 0.185), (0, 0, 0), name=name); bevel(b, 0.004, 2, 30); parts.append(b)
    pl = cube((0.07, 0.006, 0.022), (0, -0.027, 0.06)); setmat(pl, M_brass); parts.append(pl)
    for dx in (-0.035, 0.035):
        k = cyl(0.012, 0.01, (dx, -0.028, -0.01), (math.pi / 2, 0, 0), 24); setmat(k, M_chrome); parts.append(k)
        kh = cube((0.004, 0.004, 0.012), (dx, -0.034, -0.012)); setmat(kh, M_keyhole); parts.append(kh)
    setmat(b, M_box)
    for o in parts:
        o.select_set(True)
    C.view_layer.objects.active = b
    bpy.ops.object.join()
    for m in list(b.modifiers):
        select_only(b); bpy.ops.object.modifier_apply(modifier=m.name)
    return b

def box_wall(cols, rows, loc, rotz):
    u = box_unit('gavetas')
    a1 = u.modifiers.new('ax', 'ARRAY'); a1.use_relative_offset = False; a1.use_constant_offset = True; a1.constant_offset_displace = (0.268, 0, 0); a1.count = cols
    a2 = u.modifiers.new('az', 'ARRAY'); a2.use_relative_offset = False; a2.use_constant_offset = True; a2.constant_offset_displace = (0, 0, 0.198); a2.count = rows
    u.location = loc; u.rotation_euler = (0, 0, rotz)
    return u

box_wall(18, 15, (-2.28, 4.98, 0.2), 0)
box_wall(15, 15, (-2.42, 0.98, 0.2), math.pi / 2)
box_wall(15, 15, (2.42, 4.75, 0.2), -math.pi / 2)

M_void = metal('fundo_gaveta', (0.03, 0.03, 0.03), (0.5, 0.6))
for c_, r_ in ((3, 11), (4, 7), (5, 13), (6, 9), (7, 12), (8, 10), (4, 10), (7, 7), (6, 12), (2, 8)):
    bx = -2.28 + c_ * 0.268; bz = 0.2 + r_ * 0.198; yf = 4.955
    cav = cube((0.236, 0.01, 0.168), (bx, yf - 0.002, bz)); setmat(cav, M_void)
    th = math.radians(random.choice((-95, -110, -125)))
    hx = bx - 0.1275
    dr = cube((0.255, 0.012, 0.185), (hx + math.cos(th) * 0.1275, yf - 0.006 + math.sin(th) * 0.1275, bz), (0, 0, th)); bevel(dr, 0.003, 2); setmat(dr, M_box)
    pl = cube((0.07, 0.006, 0.022), (hx + math.cos(th) * 0.1275 - math.sin(th) * -0.009, yf - 0.006 + math.sin(th) * 0.1275 + math.cos(th) * -0.009, bz + 0.06), (0, 0, th)); setmat(pl, M_brass)

# mesa
top = cube((1.7, 0.85, 0.04), (0.1, 2.55, 0.9), name='mesa'); bevel(top, 0.006, 3); setmat(top, M_stainless)
for sx in (-0.78, 0.78):
    for sy in (-0.36, 0.36):
        l = cyl(0.022, 0.88, (0.1 + sx, 2.55 + sy, 0.44), verts=24); setmat(l, M_stainless); smooth(l)
shelf = cube((1.6, 0.78, 0.025), (0.1, 2.55, 0.22)); setmat(shelf, M_stainless)

# barras de ouro (trapezoidais)
def gold_bar():
    me = bpy.data.meshes.new('barra'); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    for v in bm.verts:
        v.co.x *= 0.25; v.co.y *= 0.085; v.co.z *= 0.048
        if v.co.z > 0:
            v.co.x *= 0.86; v.co.y *= 0.78
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new('barra', me); C.collection.objects.link(o)
    bevel(o, 0.004, 3, 30); setmat(o, M_gold); smooth(o, 30)
    return o
proto = gold_bar()
gold_objs = []
for layer in range(4):
    nx, ny = 4 - layer, 3 - (layer > 1)
    for ix in range(nx):
        for iy in range(ny):
            o = proto.copy(); C.collection.objects.link(o)
            o.location = (-0.3 + (ix - (nx - 1) / 2) * 0.255 + random.uniform(-.004, .004), 2.5 + (iy - (ny - 1) / 2) * 0.092, 0.92 + 0.024 + layer * 0.048)
            o.rotation_euler = (0, 0, random.uniform(-0.015, 0.015) + (math.pi / 2 if layer % 2 and False else 0))
bpy.data.objects.remove(proto, do_unlink=True)

# maços de dinheiro
def bundle_mesh():
    me = bpy.data.meshes.new('maco'); bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    for v in bm.verts:
        v.co.x *= 0.158; v.co.y *= 0.068; v.co.z *= 0.021
    uv = bm.loops.layers.uv.new()
    for f in bm.faces:
        for lp in f.loops:
            lp[uv].uv = (lp.vert.co.x / 0.158 + 0.5, lp.vert.co.y / 0.068 + 0.5)
    bm.to_mesh(me); bm.free()
    return me
B_ME = bundle_mesh()
BAND = bpy.data.meshes.new('cinta'); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1)
for v in bm.verts:
    v.co.x *= 0.03; v.co.y *= 0.0695; v.co.z *= 0.0218
bm.to_mesh(BAND); bm.free()

def bundle(x, y, z, rz):
    o = bpy.data.objects.new('maco', B_ME); C.collection.objects.link(o); setmat(o, M_cash) if not o.data.materials else None
    o.location = (x, y, z); o.rotation_euler = (0, 0, rz)
    b = bpy.data.objects.new('cinta', BAND); C.collection.objects.link(b)
    if not b.data.materials: b.data.materials.append(M_band)
    b.parent = o
    return o

def money_block(cx, cy, z0, nx, ny, nz, rz=0.0):
    cs, sn = math.cos(rz), math.sin(rz)
    for k in range(nz):
        for i in range(nx):
            for j in range(ny):
                if k >= nz - 1 and (i + j) % 3 == 0:
                    continue
                ox = (i - (nx - 1) / 2) * 0.162; oy = (j - (ny - 1) / 2) * 0.072
                bundle(cx + ox * cs - oy * sn + random.uniform(-.003, .003), cy + ox * sn + oy * cs + random.uniform(-.003, .003), z0 + 0.0106 + k * 0.0213, rz + random.uniform(-0.03, 0.03))

money_block(0.48, 2.52, 0.92, 4, 8, 9, 0.0)
money_block(0.3, 2.55, 0.235, 6, 9, 4, 0.0)

# carrinhos laterais cheios de dinheiro
def cart(cx, cy, rz):
    for z in (0.28, 0.82):
        s = cube((1.1, 0.62, 0.03), (cx, cy, z), (0, 0, rz)); bevel(s, 0.005, 2); setmat(s, M_stainless)
    cs, sn = math.cos(rz), math.sin(rz)
    for sx in (-0.52, 0.52):
        for sy in (-0.28, 0.28):
            l = cyl(0.018, 0.84, (cx + sx * cs - sy * sn, cy + sx * sn + sy * cs, 0.42), verts=20); setmat(l, M_stainless); smooth(l)
    money_block(cx, cy, 0.835, 6, 8, 11, rz)
    money_block(cx, cy, 0.295, 6, 8, 6, rz)
cart(-1.6, 2.3, 0.3)
cart(1.75, 2.1, -0.35)
for c_, r_ in ((8, 9), (10, 12), (11, 6), (13, 10), (9, 5)):
    by = 0.98 + c_ * 0.268; bz = 0.2 + r_ * 0.198; xf = -2.42 + 0.025
    cav = cube((0.01, 0.236, 0.168), (xf + 0.002, by, bz)); setmat(cav, M_void)
    ph = math.radians(random.choice((-5, -20, -35)))
    hy = by - 0.1275
    dr = cube((0.255, 0.012, 0.185), (xf + 0.006 + math.cos(ph) * 0.1275, hy + math.sin(ph) * 0.1275, bz), (0, 0, ph)); bevel(dr, 0.003, 2); setmat(dr, M_box)
money_block(1.05, 1.25, 0.0, 4, 5, 5, 0.45)
money_block(-1.05, 1.1, 0.0, 3, 4, 3, -0.3)
for k in range(5):
    o = bundle(random.uniform(-0.5, 1.4), random.uniform(0.75, 1.9), 0.0106, random.uniform(0, math.tau))
o = bundle(0.35, -0.35, 0.0106, 0.7)

# cédulas soltas no chão, perto da porta
note_me = bpy.data.meshes.new('cedula'); bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=8, y_segments=4, size=0.5)
uvl = bm.loops.layers.uv.new()
for f in bm.faces:
    for lp in f.loops:
        lp[uvl].uv = (lp.vert.co.x + 0.5, lp.vert.co.y + 0.5)
for v in bm.verts:
    v.co.x *= 0.156 / 1.0; v.co.y *= 0.066 / 1.0
bm.to_mesh(note_me); bm.free()
note_me.materials.append(M_cash)
for i in range(30):
    o = bpy.data.objects.new('cedula', note_me); C.collection.objects.link(o)
    t_ = random.random()
    o.location = (random.uniform(-0.9, 1.4) + (0.3 if t_ < 0.3 else 0), random.uniform(0.2, 2.6) if t_ > 0.3 else random.uniform(-0.7, 0.3), 0.002 + i * 0.0003)
    o.rotation_euler = (random.uniform(-0.04, 0.04), random.uniform(-0.04, 0.04), random.uniform(0, math.tau))
    m = o.modifiers.new('solid', 'SOLIDIFY'); m.thickness = 0.0003
    d = o.modifiers.new('curva', 'SIMPLE_DEFORM'); d.deform_method = 'BEND'; d.angle = random.uniform(-0.5, 0.5); d.deform_axis = 'Y'

# ---------------- porta (aberta, mostrando o mecanismo interno) ----------------
pivot = bpy.data.objects.new('dobradica', None); C.collection.objects.link(pivot)
pivot.location = (-1.24, -0.27, CZ)
door = bpy.data.objects.new('porta', None); C.collection.objects.link(door)
door.parent = pivot; door.location = (1.24, 0.32, 0)   # centro da porta quando fechada: (0, 0.05, CZ)

def dpart(o):
    # converte de coordenadas "locais da porta" (centro na origem) para filhos da porta
    o.parent = door
    return o

def at(x, y, z):
    return (x, y, z)

slab = dpart(cyl(R, 0.46, (0, 0, 0), (math.pi / 2, 0, 0), 192, 'chapa')); bevel(slab, 0.03, 5); setmat(slab, M_steel); smooth(slab)
for r_, d_, y_ in ((1.0, 0.03, -0.24), (0.62, 0.035, -0.272)):
    o = dpart(cyl(r_, d_, (0, y_, 0), (math.pi / 2, 0, 0), 160)); bevel(o, 0.008, 3); setmat(o, M_steel); smooth(o)
for i in range(36):
    a = i / 36 * math.tau
    s = dpart(sphere(0.02, (math.cos(a) * 1.045, -0.232, math.sin(a) * 1.045), 16)); s.scale = (1, 0.5, 1); setmat(s, M_chrome); smooth(s)
hub = dpart(cyl(0.15, 0.1, (0, -0.33, 0), (math.pi / 2, 0, 0), 64)); bevel(hub, 0.01, 3); setmat(hub, M_chrome); smooth(hub)
wheel = dpart(torus(0.47, 0.023, (0, -0.44, 0), (math.pi / 2, 0, 0))); setmat(wheel, M_chrome); smooth(wheel)
for i in range(3):
    sp = dpart(cyl(0.014, 0.94, (0, -0.44, 0), (0, i * math.pi / 3, 0), 24)); setmat(sp, M_chrome); smooth(sp)
for i in range(6):
    a = i / 6 * math.tau
    h = dpart(cyl(0.018, 0.16, (math.cos(a) * 0.5, -0.52, math.sin(a) * 0.5), (math.pi / 2, 0, 0), 24)); setmat(h, M_chrome); smooth(h)
    c = dpart(sphere(0.028, (math.cos(a) * 0.5, -0.6, math.sin(a) * 0.5), 24)); setmat(c, M_chrome); smooth(c)
# lado de dentro: tampa, engrenagem, barras e ferrolhos estendidos
back = dpart(cyl(0.9, 0.18, (0, 0.32, 0), (math.pi / 2, 0, 0), 160, 'tampa')); bevel(back, 0.012, 3); setmat(back, M_steel_dark); smooth(back)
gear = dpart(cyl(0.22, 0.06, (0, 0.44, 0), (math.pi / 2, 0, 0), 96, 'engrenagem')); bevel(gear, 0.006, 2); setmat(gear, M_brass); smooth(gear)
for i in range(28):
    a = i / 28 * math.tau
    t = dpart(cube((0.03, 0.06, 0.03), (math.cos(a) * 0.235, 0.44, math.sin(a) * 0.235), (0, -a, 0))); setmat(t, M_brass)
for i in range(10):
    a = i / 10 * math.tau + math.pi / 10
    ca, sa = math.cos(a), math.sin(a)
    bar = dpart(cube((0.62, 0.035, 0.05), (ca * 0.56, 0.43, sa * 0.56), (0, -a, 0))); bevel(bar, 0.005, 2); setmat(bar, M_steel)
    pin = dpart(cyl(0.022, 0.05, (ca * 0.27, 0.46, sa * 0.27), (math.pi / 2, 0, 0), 24)); setmat(pin, M_chrome)
    g = dpart(cube((0.09, 0.08, 0.1), (ca * 0.94, 0.39, sa * 0.94), (0, -a, 0))); bevel(g, 0.006, 2); setmat(g, M_steel_dark)
    bolt = dpart(cyl(0.047, 0.36, (ca * (R + 0.06), 0.0, sa * (R + 0.06)), (0, math.pi / 2 - a, 0), 48, 'ferrolho'))
    bevel(bolt, 0.01, 3); setmat(bolt, M_chrome); smooth(bolt)
if not os.environ.get('NOPLATE'):
    # placa do fabricante com o logo
    plate = dpart(cube((0.6, 0.008, 0.18), (0, 0.475, 0.6), name='placa')); bevel(plate, 0.004, 2)
    plate.data.materials.append(M_logo)
    bm = bmesh.new(); bm.from_mesh(plate.data); uvl = bm.loops.layers.uv.verify()
    xs = [v.co.x for v in bm.verts]; zs = [v.co.z for v in bm.verts]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    print('placa', x0, x1, z0, z1)
    for f in bm.faces:
        for lp in f.loops:
            lp[uvl].uv = (1 - (lp.vert.co.x - x0) / (x1 - x0), (lp.vert.co.z - z0) / (z1 - z0))
    bm.to_mesh(plate.data); bm.free()
    for dx in (-0.27, 0.27):
        for dz in (-0.07, 0.07):
            s = dpart(sphere(0.009, (dx, 0.48, 0.6 + dz), 12)); setmat(s, M_chrome)
            so = dpart(cyl(0.008, 0.03, (dx, 0.46, 0.6 + dz), (math.pi / 2, 0, 0), 12)); setmat(so, M_chrome)

# dobradiças
for dz in (-0.62, 0.62):
    h = cyl(0.11, 0.42, (-1.24, -0.27, CZ + dz), verts=64, name='dobradica'); bevel(h, 0.01, 3); setmat(h, M_steel_dark); smooth(h)
    arm = cube((0.5, 0.12, 0.16), (0.25, 0.0, dz), name='braco'); arm.parent = pivot; bevel(arm, 0.01, 3); setmat(arm, M_steel_dark)
    plate_w = cube((0.12, 0.14, 0.5), (-1.24, -0.12, CZ + dz)); bevel(plate_w, 0.01, 2); setmat(plate_w, M_steel_dark)

pivot.rotation_euler = (0, 0, math.radians(-104))

# ---------------- luz ----------------
world = bpy.data.worlds.new('mundo'); scene.world = world; world.use_nodes = True
wn = world.node_tree; bg = wn.nodes.get('Background')
env = wn.nodes.new('ShaderNodeTexEnvironment'); env.image = bpy.data.images.load(os.path.join(HERE, 'lobby.exr'))
mp = wn.nodes.new('ShaderNodeMapping'); tcw = wn.nodes.new('ShaderNodeTexCoord'); mp.inputs['Rotation'].default_value[2] = math.radians(140)
wn.links.new(tcw.outputs['Generated'], mp.inputs['Vector']); wn.links.new(mp.outputs['Vector'], env.inputs['Vector'])
wn.links.new(env.outputs['Color'], bg.inputs['Color']); bg.inputs['Strength'].default_value = 0.2

def area(name, loc, rot, size, power, color, shape='RECTANGLE', sy=None):
    l = bpy.data.lights.new(name, 'AREA'); l.energy = power; l.color = color; l.shape = shape; l.size = size
    if sy: l.size_y = sy
    o = bpy.data.objects.new(name, l); C.collection.objects.link(o); o.location = loc; o.rotation_euler = rot
    return o

area('teto_cofre', (0.1, 2.7, 3.15), (0, 0, 0), 3.2, 820, (1.0, 0.8, 0.58), sy=2.6)
area('fundo_cofre', (0, 4.6, 2.6), (math.radians(60), 0, 0), 1.6, 90, (1.0, 0.86, 0.7))
key = area('principal', (-0.6, -3.6, 4.6), (0, 0, 0), 1.6, 330, (1.0, 0.95, 0.9))
kt = bpy.data.objects.new('alvo_luz', None); C.collection.objects.link(kt); kt.location = (-0.7, -0.6, 1.1)
c_ = key.constraints.new('TRACK_TO'); c_.target = kt; c_.track_axis = 'TRACK_NEGATIVE_Z'; c_.up_axis = 'UP_Y'
area('preenchimento', (-3.4, -3.6, 1.9), (math.radians(80), 0, math.radians(-50)), 2.5, 40, (0.86, 0.9, 1.0))
area('contra', (-2.6, 1.2, 3.4), (math.radians(-40), math.radians(-30), 0), 1.2, 120, (1.0, 0.9, 0.8))

if os.environ.get('HAZE'):
    vm = bpy.data.materials.new('nevoa'); vm.use_nodes = True
    vn = vm.node_tree; vn.nodes.remove(vn.nodes.get('Principled BSDF'))
    pv = vn.nodes.new('ShaderNodeVolumePrincipled'); pv.inputs['Density'].default_value = float(os.environ.get('HAZE'))
    pv.inputs['Anisotropy'].default_value = 0.55; pv.inputs['Color'].default_value = (1.0, 0.97, 0.93, 1)
    vn.links.new(pv.outputs['Volume'], vn.nodes.get('Material Output').inputs['Volume'])
    dom = cube((9, 3.6, 3.35), (0, -1.1, 1.67), name='nevoa'); setmat(dom, vm)
    for ob in bpy.data.objects:
        if ob.type == 'LIGHT' and ob.name in ('principal', 'preenchimento'):
            ob.data.energy *= float(os.environ.get('EXT', '0.55'))
    bg.inputs['Strength'].default_value = 0.12
    sp = bpy.data.lights.new('feixe', 'SPOT'); sp.energy = float(os.environ.get('SPOT', '1800')); sp.color = (1.0, 0.8, 0.55); sp.spot_size = math.radians(42); sp.spot_blend = 0.5; sp.shadow_soft_size = 0.25
    so = bpy.data.objects.new('feixe', sp); C.collection.objects.link(so); so.location = (0.25, 4.6, 2.9)
    st = bpy.data.objects.new('alvo_feixe', None); C.collection.objects.link(st); st.location = (-0.4, -2.2, 0.0)
    ct = so.constraints.new('TRACK_TO'); ct.target = st; ct.track_axis = 'TRACK_NEGATIVE_Z'; ct.up_axis = 'UP_Y'
    scene.cycles.volume_bounces = 0
    try: scene.cycles.volume_step_rate = 2.0
    except Exception: pass

# ---------------- câmera ----------------
cam_d = bpy.data.cameras.new('cam'); cam = bpy.data.objects.new('cam', cam_d); C.collection.objects.link(cam)
cam.location = (2.6, -5.6, 1.45)
target = bpy.data.objects.new('alvo', None); C.collection.objects.link(target); target.location = (-0.55, 0.6, 1.1)
tr = cam.constraints.new('TRACK_TO'); tr.target = target; tr.track_axis = 'TRACK_NEGATIVE_Z'; tr.up_axis = 'UP_Y'
cam_d.lens = float(os.environ.get('LENS', '30')); cam_d.sensor_width = 36; cam_d.shift_x = float(os.environ.get('SHIFTX', '0'))
cam_d.dof.use_dof = True; cam_d.dof.aperture_fstop = 5.6
focus = bpy.data.objects.new('foco', None); C.collection.objects.link(focus); focus.location = (-1.0, -1.3, 1.3)
cam_d.dof.focus_object = focus
scene.camera = cam

# ---------------- render ----------------
r = scene.render; r.engine = 'CYCLES'
cy = scene.cycles; cy.device = 'CPU'
if Q == 'final':
    r.resolution_x, r.resolution_y = 1920, 1080; cy.samples = int(os.environ.get('SAMPLES', '320')); cy.adaptive_threshold = 0.012
elif Q == 'tiny':
    r.resolution_x, r.resolution_y = 480, 270; cy.samples = 32; cy.adaptive_threshold = 0.08
else:
    r.resolution_x, r.resolution_y = 960, 540; cy.samples = 48; cy.adaptive_threshold = 0.05
r.resolution_percentage = 100
cy.use_adaptive_sampling = True; cy.use_denoising = True
try: cy.denoiser = 'OPENIMAGEDENOISE'
except Exception: pass
cy.max_bounces = 10; cy.glossy_bounces = 6; cy.diffuse_bounces = 4; cy.transparent_max_bounces = 4
cy.caustics_reflective = False; cy.caustics_refractive = False; cy.sample_clamp_indirect = 6
r.film_transparent = False
vs = scene.view_settings
try: vs.view_transform = 'AgX'
except Exception: pass
for lk in ('AgX - Medium High Contrast', 'Medium High Contrast'):
    try:
        vs.look = lk; break
    except Exception: pass
vs.exposure = 0.0
r.image_settings.file_format = 'PNG'; r.filepath = OUT
r.threads_mode = 'AUTO'
print('objetos:', len(bpy.data.objects))
if Q == 'crop':
    r.resolution_x, r.resolution_y = 1920, 1080; cy.samples = 24
    r.use_border = True; r.use_crop_to_border = True
    r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y = 0.22, 0.36, 0.66, 0.8
bpy.ops.render.render(write_still=True)
print('salvo', OUT)
