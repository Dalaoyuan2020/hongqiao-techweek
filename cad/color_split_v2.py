"""把科鲸壳拆成多色打印件（拓竹 AMS 等多色机用），并出一个单色+描边浅槽的手绘版。

用法：.venv/bin/python cad/color_split_v2.py cad/kejing_shell_v2c.stl
输入：壳 STL + 同名 _features.json（paint 列表，由 build_kejing_v2.py 生成）
输出（同目录）：
  <name>_color_blue/white/black/pink.stl   四块互不重叠，拼起来就是整个壳；颜色只在表面 1.4 mm 深
  <name>_paintguide.stl                    单色版：颜色分界处刻 0.7 mm 宽、0.5 mm 深的描边槽
"""
import json
import sys
import time

import igl
import manifold3d as mf
import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage import measure

T0 = time.time()
stl = sys.argv[1]
F = json.load(open(stl.replace('.stl', '_features.json'), encoding='utf-8'))
R_tm = trimesh.load(stl)
WCX, BASE_FRONT_Y = -1.61, -27.84
SKIN, GROOVE_D, GROOVE_W = 1.4, 0.5, 0.7


def to_mf(tm):
    tm = tm.copy(); tm.merge_vertices()
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(tm.vertices, np.float32), tri_verts=np.asarray(tm.faces, np.uint32)))


def to_tm(man):
    mm = man.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)


R = to_mf(R_tm)

# ---------- 表层（skin）：离外表面 d mm 以内的薄层，用于限定颜色/刻槽深度 ----------
h = 0.35
lo = np.array([-62.0, -60.0, -1.0]); hi = np.array([62.0, 20.0, 104.0])   # 正面区域，颜色都在这里
g = [np.arange(l, u + h, h) for l, u in zip(lo, hi)]
Q = np.stack(np.meshgrid(*g, indexing='ij'), -1).reshape(-1, 3)
V = np.asarray(R_tm.vertices, float); Fc = np.asarray(R_tm.faces, np.int64)
inside = (igl.fast_winding_number(V, Fc, Q) > 0.5).reshape([len(x) for x in g])
# 只算「看得见的外表面」：把底座腔体和斜顶空腔当成实心，内壁就不会被上色/刻槽
CAV = ((-36.61, 33.39), (BASE_FRONT_Y - 0.45, 41.66), (-2.0, 75.0))
cav3 = ((g[0][:, None, None] > CAV[0][0]) & (g[0][:, None, None] < CAV[0][1]) & (g[1][None, :, None] > CAV[1][0])
        & (g[1][None, :, None] < CAV[1][1]) & (g[2][None, None, :] < CAV[2][1]))
inside |= cav3
D = (ndimage.distance_transform_edt(~inside) - ndimage.distance_transform_edt(inside)) * h
band = np.argwhere(np.abs(D) < 2.5)
pts, _ = trimesh.sample.sample_surface(R_tm, 2_500_000, seed=5)
in_cav = ((pts[:, 0] > CAV[0][0] - 0.3) & (pts[:, 0] < CAV[0][1] + 0.3) & (pts[:, 1] > CAV[1][0] - 0.3)
          & (pts[:, 1] < CAV[1][1] + 0.3) & (pts[:, 2] < CAV[2][1]))
pts = pts[~in_cav]
dist, _ = cKDTree(pts).query(np.c_[g[0][band[:, 0]], g[1][band[:, 1]], g[2][band[:, 2]]], workers=-1)
D[band[:, 0], band[:, 1], band[:, 2]] = np.sign(D[band[:, 0], band[:, 1], band[:, 2]]) * dist
print(f'sdf {time.time()-T0:.0f}s')


def skin(depth):
    f = np.maximum(D - 1.0, -(D + depth)).astype(np.float32)   # 外侧多出 1 mm，交上壳后外表面就是壳本身，不出碎片
    f[0] = f[-1] = 1; f[:, 0] = f[:, -1] = 1; f[:, :, 0] = f[:, :, -1] = 1
    v, fa, _, _ = measure.marching_cubes(f, 0.0, spacing=(h, h, h))
    m = trimesh.Trimesh(v + lo, fa, process=False)
    if m.volume < 0:
        m.invert()
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))


S14, S05 = skin(SKIN), skin(GROOVE_D)
print(f'skins {time.time()-T0:.0f}s status {S14.status()} {S05.status()}')


def sphere(c, r):
    return mf.Manifold.sphere(r, 64).translate(list(c))


def ellip_cyl_y(cx, cz, rx, rz, y0, y1):
    """沿 Y 的椭圆柱"""
    return mf.Manifold.cylinder(y1 - y0, 1.0, 1.0, 128).scale([rx, rz, 1.0]).rotate([-90, 0, 0]).translate([cx, y0, cz])


def box(x0, x1, y0, y1, z0, z1):
    return mf.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def prism_xz(poly, y0, y1, offset=0.0):
    """X–Z 平面多边形沿 Y 拉伸成柱体（y0<y1）；offset>0 向外扩、<0 向内缩"""
    cs = mf.CrossSection([np.asarray(poly, float).tolist()], mf.FillRule.NonZero)   # 轮廓是顺时针的，用 NonZero
    if offset:
        cs = cs.offset(offset, mf.JoinType.Round)
    # 在 XY 平面画 (x, z)，沿 +Z 拉伸 L，再绕 X 转 +90°：(x, z, t) → (x, -t, z)
    return cs.extrude(y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])


def cyl_y(cx, cz, r, y0, y1):
    return mf.Manifold.cylinder(y1 - y0, r, r, 48).rotate([-90, 0, 0]).translate([cx, y0, cz])


paint = {it['name']: it for it in F['paint']}
pf = F['plate_front_y']
# 区域（只是体积，最后再和表层、壳求交）
belly = paint['belly']; bp = np.array(belly['p']); brx, brz = belly['r']
BELLY_PLANE = pf - 1.8                     # 白肚只上在屏幕板这一层；往前凸出来的鳍保持蓝色
reg_white = ellip_cyl_y(bp[0], bp[2], brx, brz, BELLY_PLANE, bp[1] + 18)
reg_black, reg_pink, reg_hl = mf.Manifold(), mf.Manifold(), mf.Manifold()
groove_rings = []
for name, it in paint.items():
    p = np.array(it['p'])
    if 'poly' in it:                                   # 真实轮廓（cad/face_features.py 测出来的）
        yf = it['y_front']; reg = prism_xz(it['poly'], yf - 6, yf + 6)
        if name.startswith('eye'):
            reg_black += reg
            hx, hz, hr = it['highlight']; reg_hl += cyl_y(hx, hz, hr, yf - 6, yf + 6)
        elif name == 'mouth':
            reg_black += reg                                  # 嘴里面：深色（和眼睛同一种黑）
        else:
            reg_pink += reg                                   # 腮红、舌头：粉
        groove_rings.append(prism_xz(it['poly'], yf - 6, yf + 6, GROOVE_W / 2) - prism_xz(it['poly'], yf - 7, yf + 7, -GROOVE_W / 2))
        continue
    if name.startswith('eye'):
        r = it['r']; reg_black += sphere(p, r)
        reg_hl += sphere(p + np.array([r * 0.35, -1.0, r * 0.35]), r * 0.28)
        groove_rings.append(sphere(p, r + GROOVE_W / 2) - sphere(p, r - GROOVE_W / 2))
    elif name.startswith('blush') or name.startswith('mouth'):
        r = it['r']; reg_pink += sphere(p, r)
        groove_rings.append(sphere(p, r + GROOVE_W / 2) - sphere(p, r - GROOVE_W / 2))
tunnel_in = box(WCX - 24.5, WCX + 24.5, pf + 0.4, BASE_FRONT_Y - 0.05, 1.5, 50)
reg_black += tunnel_in
groove_rings.append((ellip_cyl_y(bp[0], bp[2], brx + GROOVE_W / 2, brz + GROOVE_W / 2, BELLY_PLANE, bp[1] + 18)
                     - ellip_cyl_y(bp[0], bp[2], brx - GROOVE_W / 2, brz - GROOVE_W / 2, BELLY_PLANE - 1, bp[1] + 19)) - box(WCX - 26, WCX + 26, -80, 0, 0, 52))

# ---------- 多色件：互不重叠 ----------
black = (S14 ^ reg_black) ^ R
hl = ((S14 ^ reg_hl) ^ R) - (S14 ^ tunnel_in)
pink = ((S14 ^ reg_pink) ^ R)
black = black - pink
white = (((S14 ^ reg_white) ^ R) - black - pink) + hl
black = black - hl
blue = R - white - black - pink
out = {}
for name, man in (('blue', blue), ('white', white), ('black', black), ('pink', pink)):
    t = to_tm(man)
    keep = [q for q in t.split(only_watertight=False) if q.volume > 1.0]      # 丢掉布尔运算留下的零厚度碎片
    t = trimesh.util.concatenate(keep); t.export(stl.replace('.stl', f'_color_{name}.stl')); out[name] = t
    print(f'{name}: vol {t.volume/1000:.2f} cm3, watertight {t.is_watertight}, bodies {len(t.split(only_watertight=False))}')
tot = sum(t.volume for t in out.values())
print(f'sum of parts {tot/1000:.2f} cm3 vs shell {R_tm.volume/1000:.2f} cm3 (diff {abs(tot - R_tm.volume):.1f} mm3)')

# ---------- 单色描边版 ----------
grooves = mf.Manifold()
for gr in groove_rings:
    grooves += gr
pg = to_tm(R - (S05 ^ grooves))
pg.export(stl.replace('.stl', '_paintguide.stl'))
print(f'paintguide: vol {pg.volume/1000:.2f} cm3 watertight {pg.is_watertight}; total {time.time()-T0:.0f}s')
