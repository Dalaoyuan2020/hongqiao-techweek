"""科鲸壳 v1 生成脚本：造型区用 SDF 雕科鲸，接口区从原壳网格精确保留。

用法：.venv/bin/python cad/build_kejing.py [--res 0.45] [--out cad/kejing_shell_v1.stl]
输入：models/01-shell.stl（奶龙原壳，不入库）
思路：
  结果 = (科鲸造型 W − 禁区 E) ∪ 保留区 K
  K = 原壳 ∩ 接口盒（底座四周 3 mm 墙 + 顶板）∪ 原壳 ∩ 卡销圆柱（r=9）
  E = (接口盒 − 原壳) ∪ (卡销通道圆柱 r=6.5 − 原壳) ∪ 卡销帽通道 ∪ Z<0
所有接口尺寸都来自对原壳/底座的实测（见 docs/shell_interface_measured.md）。
"""
import argparse
import time

import manifold3d as mf
import numpy as np
import trimesh
from skimage import measure

T0 = time.time()
ap = argparse.ArgumentParser()
ap.add_argument('--res', type=float, default=0.45)
ap.add_argument('--out', default='cad/kejing_shell_v1.stl')
ap.add_argument('--orig', default='models/01-shell.stl')
args = ap.parse_args()

# ---------------- 实测接口（原壳坐标系：前 = -Y，上 = +Z，底面 Z=0） ----------------
BASE_OFF = np.array([-1.61, 6.66, 0.0])       # 底座在原壳里的位置（四周各 0.5 mm 间隙）
CAV_X = (-36.61, 33.39); CAV_Y_BACK = 41.66; CAV_TOP = 42.5
BASE_FRONT_Y = -27.84                          # 底座正面（屏幕面）
WIN_X = (-15.61, 12.39); WIN_Z = (8.0, 37.5)   # 底座正面屏幕窗口
SMALL_HOLE = (16.39, 27.25)                    # 底座正面右侧 Ø1 小孔（麦克风/传感器，保持通气）
PIN_Y, PIN_Z = 6.66, 28.0                      # 卡销通道轴线（沿 X）
BOSS_FACE_X = 53.8                             # 原壳侧面卡销凸台外端面
KEEP_BOX = ((-39.6, 36.4), (-28.3, 44.7), (-1.0, 45.5))

# ---------------- 造型参数（改造型只动这里） ----------------
BODY_C = np.array([0.0, 2.5, 50.5]); BODY_R = np.array([45.5, 45.0, 50.5])
SKIRT = ((-48.0, 44.8), (-36.5, 50.5), (-6.5, 46.0)); SKIRT_RAD = 18.0; SKIRT_ZRAD = 5.0; SKIRT_K = 12.0  # 竖边大圆角，底边小圆角（Z=0 处仍包住接口盒）
FRONT_FLAT_Y = -36.5; FRONT_FLAT_Z = 50.0; FRONT_FLAT_K = 6.0   # 屏幕前方肚皮压平，屏幕不至于陷太深
BELLY_C2 = (-1.6, 24.0); BELLY_R2 = (37.0, 40.0); BELLY_UP = 1.2
FIN_PATH = ((78.0, 40.0, 2.5), (52.0, 36.0, 4.0))   # (方位角°, 高度 Z, 离表面) 肩→肘
FIN_HAND = (33.5, 31.0, 5.5)                         # (相对屏幕中线 X, Z, 离表面)
TOP_FLAT_Z = 100.0
EYE = dict(x=20.0, z=80.0, dia=17.0, bulge=2.8)
MOUTH = dict(c1=(74.0, 20.0), c2=(84.0, 24.0), depth=2.0)
MAGNET = dict(dia=10.4, depth=2.4)             # Ø10×2 磁铁，帽子/水柱共用
FLAG = dict(dia=3.3, depth=12.0, tilt=32.0)    # 导游旗杆 Ø3，向前倾 32° 避开头部
TUNNEL_MARGIN = 1.0; TUNNEL_MARGIN_X = 5.3; TUNNEL_CORNER = 4.0; FLARE_SIDE = 0.25;  # 横向放宽到把右侧小孔一起让出来（不留薄筋）
FLARE_TOP = 0.8; FLARE_BOT = 0.35
RIM_W = 3.0; RIM_UP = 1.3

h = args.res
gx = np.arange(-68, 68 + h, h, dtype=np.float32)
gy = np.arange(-64, 80 + h, h, dtype=np.float32)
gz = np.arange(-9, 122 + h, h, dtype=np.float32)
X = gx[:, None, None]; Y = gy[None, :, None]; Z = gz[None, None, :]
print(f'grid {len(gx)}x{len(gy)}x{len(gz)} = {len(gx)*len(gy)*len(gz)/1e6:.1f}M @ {h} mm')


def sub(b):
    """bbox ((x0,x1),(y0,y1),(z0,z1)) -> slices + broadcast coords of that sub-grid"""
    sl = []
    for (lo, hi), g in zip(b, (gx, gy, gz)):
        i0 = max(int(np.searchsorted(g, lo)) - 1, 0); i1 = min(int(np.searchsorted(g, hi)) + 1, len(g))
        sl.append(slice(i0, i1))
    return tuple(sl), gx[sl[0]][:, None, None], gy[sl[1]][None, :, None], gz[sl[2]][None, None, :]


def ellipsoid(x, y, z, c, r):
    px, py, pz = (x - c[0]) / r[0], (y - c[1]) / r[1], (z - c[2]) / r[2]
    k0 = np.sqrt(px * px + py * py + pz * pz)
    k1 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-6)


def round_box(x, y, z, b, rad):
    c = [(lo + hi) / 2 for lo, hi in b]; hh = [(hi - lo) / 2 - rad for lo, hi in b]
    qx = np.abs(x - c[0]) - hh[0]; qy = np.abs(y - c[1]) - hh[1]; qz = np.abs(z - c[2]) - hh[2]
    out = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2 + np.maximum(qz, 0) ** 2)
    return out + np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0) - rad


def round_prism(x, y, z, b, r_xy, r_z):
    """竖边圆角 r_xy、上下边圆角 r_z 的圆角柱体"""
    c = [(lo + hi) / 2 for lo, hi in b]; hh = [(hi - lo) / 2 for lo, hi in b]
    qx = np.abs(x - c[0]) - (hh[0] - r_xy); qy = np.abs(y - c[1]) - (hh[1] - r_xy)
    d2 = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - r_xy
    dz = np.abs(z - c[2]) - hh[2]
    a_, b_ = d2 + r_z, dz + r_z
    return np.sqrt(np.maximum(a_, 0) ** 2 + np.maximum(b_, 0) ** 2) + np.minimum(np.maximum(a_, b_), 0) - r_z


def smin(a, b, k):
    hh = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - hh) + a * hh - k * hh * (1 - hh)


def oriented_ellipsoid(x, y, z, c, axes, r):
    """axes: 3 orthonormal vectors (local x,y,z), r: radii along them"""
    dx, dy, dz = x - c[0], y - c[1], z - c[2]
    l = [dx * a[0] + dy * a[1] + dz * a[2] for a in axes]
    return ellipsoid(l[0], l[1], l[2], (0, 0, 0), r)


def round_rect2(u, v, hu0, hu1, hv0, hv1, rad):
    """2D rounded rect with per-side extents: u in [-hu0, hu1], v in [-hv0, hv1] (around origin)"""
    cu = (hu1 - hu0) / 2; cv = (hv1 - hv0) / 2
    qu = np.abs(u - cu) - ((hu0 + hu1) / 2 - rad); qv = np.abs(v - cv) - ((hv0 + hv1) / 2 - rad)
    return np.sqrt(np.maximum(qu, 0) ** 2 + np.maximum(qv, 0) ** 2) + np.minimum(np.maximum(qu, qv), 0) - rad


def surface_y(x, z):
    """front surface Y of the body ellipsoid at (x, z) (approx, for placing face features)"""
    t = 1 - ((x - BODY_C[0]) / BODY_R[0]) ** 2 - ((z - BODY_C[2]) / BODY_R[2]) ** 2
    return BODY_C[1] - BODY_R[1] * np.sqrt(max(t, 0))


from scipy.ndimage import map_coordinates
ORIGIN = np.array([gx[0], gy[0], gz[0]])


def sample(D, pts):
    pts = np.atleast_2d(np.asarray(pts, float))
    return map_coordinates(D, ((pts - ORIGIN) / h).T, order=1, mode='nearest')


def hit(D, p_out, d):
    """从外面 p_out 沿 d 往里走，返回第一个进入实体的点"""
    d = np.asarray(d, float); d /= np.linalg.norm(d)
    ts = np.arange(0, 120, 0.1); pts = np.asarray(p_out, float) + ts[:, None] * d
    v = sample(D, pts); i = int(np.argmax(v < 0)); assert v[i] < 0, ('miss', p_out, d)
    return pts[i]


def normal(D, p):
    e = 0.6
    g = np.array([sample(D, p + e * a)[0] - sample(D, p - e * a)[0] for a in np.eye(3)])
    return g / np.linalg.norm(g)


def smax(a, b, k):
    return -smin(-a, -b, k)


FEAT = {}   # 记录特征位置，给上色预览和检查用

# ---------- 1 身体 + 裙边（裙边包住接口盒，平滑并成梨形） ----------
D = ellipsoid(X, Y, Z, BODY_C, BODY_R).astype(np.float32)
m = SKIRT_K + 1
sl, x, y, z = sub(((SKIRT[0][0] - m, SKIRT[0][1] + m), (SKIRT[1][0] - m, SKIRT[1][1] + m), (SKIRT[2][0] - m, SKIRT[2][1] + m)))
D[sl] = smin(D[sl], round_prism(x, y, z, SKIRT, SKIRT_RAD, SKIRT_ZRAD), SKIRT_K)

# ---------- 2 屏幕前方压平（Z<50 处前脸不超过 Y=-36.5，往上逐渐放开） ----------
sl, x, y, z = sub(((-60, 60), (-64, -20), (-9, 80)))
yf = FRONT_FLAT_Y - 2.0 * np.maximum(z - FRONT_FLAT_Z, 0)
D[sl] = smax(D[sl], yf - y, FRONT_FLAT_K)

# ---------- 3 白肚皮：上嘴唇弧线以下、前面一块整体抬高 1.2 mm（上色分界） ----------
(c1z, r1), (c2z, r2) = MOUTH['c1'], MOUTH['c2']


def belly2d(x, z):
    e = (np.sqrt(((x - BELLY_C2[0]) / BELLY_R2[0]) ** 2 + ((z - BELLY_C2[1]) / BELLY_R2[1]) ** 2) - 1) * min(BELLY_R2)
    return np.maximum(e, r2 - np.sqrt((x - BODY_C[0]) ** 2 + (z - c2z) ** 2))


sl, x, y, z = sub(((-45, 42), (-64, 0), (-9, 70)))
D[sl] = np.minimum(D[sl], np.maximum(np.maximum(D[sl] - BELLY_UP, belly2d(x, z)), y + 5.0))

# ---------- 4 鱼鳍：肩（卡销凸台上方）→ 肘 → 手（抱在屏框两侧），贴着表面走 ----------
wcx = (WIN_X[0] + WIN_X[1]) / 2
FEAT['hands'] = {}
for sx in (-1, 1):
    pts, nrm = [], []
    for az, zz, off in FIN_PATH:
        a = np.radians(az); dirh = np.array([sx * np.sin(a), -np.cos(a), 0.0])
        p_out = np.array([BODY_C[0], BODY_C[1], zz]) + dirh * 90
        q = hit(D, p_out, -dirh); n = normal(D, q)
        pts.append(q + n * off); nrm.append(n)
    hx = wcx + sx * FIN_HAND[0]
    q = hit(D, [hx, -63, FIN_HAND[1]], [0, 1, 0]); n = normal(D, q)
    hand = q + n * FIN_HAND[2]; pts.append(hand); nrm.append(n)
    FEAT['hands'][sx] = (hand, n)
    seg_sdf = None
    for i in range(len(pts) - 1):
        A, B = pts[i], pts[i + 1]; u = B - A; L = np.linalg.norm(u); u /= L
        v = (nrm[i] + nrm[i + 1]) / 2; v -= u * (v @ u); v /= np.linalg.norm(v); w = np.cross(u, v)
        lo = np.minimum(A, B) - 14; hi = np.maximum(A, B) + 14
        sl, x, y, z = sub(tuple(zip(lo, hi)))
        e = oriented_ellipsoid(x, y, z, (A + B) / 2, (u, v, w), (L / 2 + 3.0, 4.0, 7.5 - 1.0 * i))
        D[sl] = smin(D[sl], e, 3.0)
    sl, x, y, z = sub(tuple(zip(hand - 12, hand + 12)))
    D[sl] = smin(D[sl], ellipsoid(x, y, z, hand, (6.5, 5.5, 7.5)), 3.0)

# ---------- 5 尾巴：背后伸出尾柄 + V 形上翘尾鳍 ----------
pb = hit(D, [0, 100, 44], [0, -1, 0])
a = pb + [0, -6, -2]; b = pb + [0, 13, 13]
sl, x, y, z = sub(((-40, 40), (pb[1] - 10, pb[1] + 34), (25, 90)))
ab = b - a; t = np.clip(((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / (ab @ ab), 0, 1)
tail = np.sqrt((x - a[0] - t * ab[0]) ** 2 + (y - a[1] - t * ab[1]) ** 2 + (z - a[2] - t * ab[2]) ** 2) - (8.5 - 3.0 * t)
for sx in (-1, 1):
    ang = np.radians(28)
    au = np.array([sx * np.cos(ang), 0.0, np.sin(ang)]); av = np.array([0, 1.0, 0]); aw = np.cross(au, av)
    lobe = oriented_ellipsoid(x, y, z, b + [sx * 11.5, 2.0, 5.5], (au, av, aw), (13.5, 3.5, 7.0))
    tail = smin(tail, lobe, 3.0)
D[sl] = smin(D[sl], tail, 5.0)

# ---------- 6 眼睛：鼓起的半球（涂黑/贴眼睛贴） ----------
FEAT['eyes'] = []
for sx in (-1, 1):
    q = hit(D, [BODY_C[0] + sx * EYE['x'], -63, EYE['z']], [0, 1, 0]); n = normal(D, q)
    a_, hb = EYE['dia'] / 2, EYE['bulge']; R = (a_ * a_ + hb * hb) / (2 * hb); cc = q + n * (hb - R)
    FEAT['eyes'].append(q)
    sl, x, y, z = sub(tuple(zip(q - R - 1, q + R + 1)))
    D[sl] = np.minimum(D[sl], np.sqrt((x - cc[0]) ** 2 + (y - cc[1]) ** 2 + (z - cc[2]) ** 2) - R)

# ---------- 7 笑嘴：月牙凹槽 2 mm（涂红） ----------
sl, x, y, z = sub(((-30, 30), (-64, 0), (45, 75)))
cres = np.maximum(np.sqrt((x - BODY_C[0]) ** 2 + (z - c1z) ** 2) - r1, r2 - np.sqrt((x - BODY_C[0]) ** 2 + (z - c2z) ** 2))
mouth = np.maximum(np.maximum(cres, -(D[sl] + MOUTH['depth'])), y - 0.0)
D[sl] = np.maximum(D[sl], -mouth)

# ---------- 8 头顶：削平台面 + 磁铁座 ----------
sl, x, y, z = sub(((-40, 40), (-40, 50), (85, 122)))
D[sl] = np.maximum(D[sl], z - TOP_FLAT_Z)
rmag = MAGNET['dia'] / 2
D[sl] = np.maximum(D[sl], -np.maximum(np.sqrt((x - BODY_C[0]) ** 2 + (y - BODY_C[1]) ** 2) - rmag, TOP_FLAT_Z - MAGNET['depth'] - z))

# ---------- 9 屏幕框：圆角方口，向外张开（俯视 35° 看得到整块屏）+ 外圈凸沿 ----------
whx = (WIN_X[1] - WIN_X[0]) / 2 + TUNNEL_MARGIN_X


def tunnel2d(x, z, s):
    s = np.maximum(s, 0)
    return round_rect2(x - wcx, z, whx + FLARE_SIDE * s, whx + FLARE_SIDE * s,
                       -(WIN_Z[0] - TUNNEL_MARGIN - FLARE_BOT * s), WIN_Z[1] + TUNNEL_MARGIN + FLARE_TOP * s, TUNNEL_CORNER)


sl, x, y, z = sub(((-45, 42), (-64, -20), (-9, 72)))
ring = np.abs(tunnel2d(x, z, BASE_FRONT_Y - y) - RIM_W / 2) - RIM_W / 2
D[sl] = np.minimum(D[sl], np.maximum(np.maximum(ring, D[sl] - RIM_UP), y - (BASE_FRONT_Y - 0.4)))
D[sl] = np.maximum(D[sl], -np.maximum(tunnel2d(x, z, BASE_FRONT_Y - y), y - (BASE_FRONT_Y + 0.2)))
assert wcx + whx >= SMALL_HOLE[0] + 1.3, '屏框开口要把右侧小孔包进去'

# ---------- 10 导游旗插孔：机器人右手（-X 侧）鳍尖，Ø3.3 深 12，向前倾 25° ----------
hand, n = FEAT['hands'][-1]
ta = np.radians(FLAG['tilt']); axis = np.array([0.0, -np.sin(ta), np.cos(ta)])
P0 = hit(D, hand + axis * 30, -axis)                 # 沿旗杆方向找到鳍尖表面
sl, x, y, z = sub(((P0[0] - 6, P0[0] + 6), (P0[1] - 30, P0[1] + 10), (P0[2] - 16, P0[2] + 40)))
dx, dy, dz = x - P0[0], y - P0[1], z - P0[2]
t = dx * axis[0] + dy * axis[1] + dz * axis[2]
rr = np.sqrt(np.maximum((dx - t * axis[0]) ** 2 + (dy - t * axis[1]) ** 2 + (dz - t * axis[2]) ** 2, 0))
e1 = np.cross(axis, [1.0, 0, 0]); e1 /= np.linalg.norm(e1); e2 = np.cross(axis, e1)
walls = []
for tt in np.arange(2.5, FLAG['depth'] + 0.01, 0.5):            # 入口 2.5 mm 以下逐层
    for ang in np.radians(np.arange(0, 360, 30)):
        dirr = np.cos(ang) * e1 + np.sin(ang) * e2
        probe = P0 - axis * tt + (FLAG['dia'] / 2 + np.arange(0, 6.01, 0.1))[:, None] * dirr
        out_ = np.nonzero(sample(D, probe) > 0)[0]
        walls.append(out_[0] * 0.1 if len(out_) else 6.0)
bot = sample(D, P0 - axis * (FLAG['depth'] + 1.2))[0]
FEAT['flag_wall'] = float(min(min(walls), 6.0 if bot < 0 else 0.0))   # 孔壁（径向）和孔底最薄处
D[sl] = np.maximum(D[sl], -np.maximum(rr - FLAG['dia'] / 2, -(t + FLAG['depth'])))
line = P0 + np.arange(12, 80, 1.0)[:, None] * axis    # 出了鳍尖之后的旗杆段
FEAT['flag'] = (P0, axis, float(sample(D, line).min()))
print('flag hole entry', np.round(P0, 1), 'pole path min clearance to body', round(FEAT['flag'][2], 2), 'mm')

assert D[0].min() > 0 and D[-1].min() > 0 and D[:, 0].min() > 0 and D[:, -1].min() > 0 and D[:, :, -1].min() > 0 and D[:, :, 0].min() > 0, "SDF touches grid boundary"
print(f'sdf done {time.time()-T0:.0f}s')

verts, faces, _, _ = measure.marching_cubes(D, level=0.0, spacing=(h, h, h))
verts += np.array([gx[0], gy[0], gz[0]])
del D
W = trimesh.Trimesh(verts, faces, process=True)
if W.volume < 0:
    W.invert()
print(f'marching cubes: {len(W.faces)} faces, watertight={W.is_watertight}, {time.time()-T0:.0f}s')


def to_mf(tm):
    tm = tm.copy(); tm.merge_vertices()
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(tm.vertices, np.float32), tri_verts=np.asarray(tm.faces, np.uint32)))


def to_tm(man):
    mm = man.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)


def box(b):
    (x0, x1), (y0, y1), (z0, z1) = b
    return mf.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def xcyl(x0, x1, r, seg=96):
    return mf.Manifold.cylinder(x1 - x0, r, r, seg).rotate([0, 90, 0]).translate([x0, PIN_Y, PIN_Z])


O = to_mf(trimesh.load(args.orig))
Wm = to_mf(W)
kbox = box(KEEP_BOX)
pin_keep = xcyl(-BOSS_FACE_X - 0.5, KEEP_BOX[0][0] + 0.5, 9.0) + xcyl(KEEP_BOX[0][1] - 0.5, BOSS_FACE_X + 0.5, 9.0)
pin_void = xcyl(-75, KEEP_BOX[0][0] + 1, 6.5) + xcyl(KEEP_BOX[0][1] - 1, 75, 6.5)
head_void = xcyl(-80, -BOSS_FACE_X + 0.05, 10.5) + xcyl(BOSS_FACE_X - 0.05, 80, 10.5)
zneg = box(((-200, 200), (-200, 200), (-50, 0)))
E = (kbox - O) + (pin_void - O) + head_void + zneg
K = (O ^ kbox) + (O ^ pin_keep)
R = ((Wm - E) + K) - zneg
print(f'booleans done {time.time()-T0:.0f}s, status {R.status()}')
res = to_tm(R)
parts = res.split(only_watertight=False)
res = max(parts, key=lambda p: p.volume)
dropped = [(round(float(p.volume), 2), np.round(p.bounds.mean(0), 1).tolist()) for p in parts if p is not res]
res.export(args.out)
R = to_mf(res)
print(f'wrote {args.out}: faces {len(res.faces)}, dropped slivers {dropped}')
for name, man in (('keep', K), ('forbidden', E - zneg)):
    to_tm(man).export(args.out.replace('.stl', f'_{name}_zone.stl'))

# ---------------- 自动检查 ----------------
orig = trimesh.load(args.orig)
rows = []


def row(item, value, target, ok):
    rows.append((item, value, target, '✅' if ok else '❌'))


row('水密 / 单一实体', f'{res.is_watertight} / {len(parts) - len(dropped)} 个', 'True / 1', res.is_watertight)
row('最低点 Z', f'{res.bounds[0][2]:.2f}', '≥ 0（不遮底部开关/BOOT/Type-C）', res.bounds[0][2] >= -1e-6)
kz = kbox + pin_keep
d1 = ((R ^ kz) - (O ^ kz)).volume(); d2 = ((O ^ kz) - (R ^ kz)).volume()
row('接口区与原壳差异', f'+{d1:.3f} / −{d2:.3f} mm³', '≈ 0', d1 < 1 and d2 < 1)
base = trimesh.load('models/02-base.stl'); base.apply_translation(BASE_OFF)
B = to_mf(base)
ob, rb = (O ^ B).volume(), (R ^ B).volume()
row('与底座干涉（装好位置）', f'{rb:.3f} mm³（原壳 {ob:.3f}）', '不大于原壳', rb <= ob + 0.5)
prism = box(((base.bounds[0][0], base.bounds[1][0]), (base.bounds[0][1], base.bounds[1][1]), (0, base.bounds[1][2])))
op, rp = (O ^ prism).volume(), (R ^ prism).volume()
row('从上往下扣的通道', f'{rp:.3f} mm³（原壳 {op:.3f}）', '不大于原壳', rp <= op + 0.5)
pins = []
for f, sx in (('models/04-pin-l.stl', -1), ('models/03-pin-r.stl', 1)):
    pm = trimesh.load(f)
    if sx < 0:
        pm.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [0, 0, 1]))
    pm.apply_translation([sx * 44.2, PIN_Y, PIN_Z - 6.5])
    pins.append(to_mf(pm))
po = sum((O ^ p).volume() for p in pins); pr = sum((R ^ p).volume() for p in pins)
row('左右卡销插入', f'{pr:.3f} mm³（原壳 {po:.3f}）', '不大于原壳', pr <= po + 0.5)
hv = (R ^ (xcyl(-75, -BOSS_FACE_X - 0.3, 9.3) + xcyl(BOSS_FACE_X + 0.3, 75, 9.3))).volume()
row('卡销帽外侧空间', f'{hv:.3f} mm³', '0', hv < 0.5)
ext_o, ext_r = orig.extents, res.extents
ratio = ext_r / ext_o
row('外形尺寸 X×Y×Z', ' × '.join(f'{a:.1f}' for a in ext_r) + ' mm', '原壳 ' + ' × '.join(f'{a:.1f}' for a in ext_o) + '，不超 +10%',
    bool(np.all(ratio <= 1.10)))
fn = res.face_normals; fc = res.triangles_center; exposed = 0.0
for ax, val, sgn in ((0, KEEP_BOX[0][0], -1), (0, KEEP_BOX[0][1], 1), (1, KEEP_BOX[1][1], 1), (2, KEEP_BOX[2][1], 1)):
    msk = (np.abs(fc[:, ax] - val) < 0.02) & (fn[:, ax] * sgn > 0.99)
    exposed += res.area_faces[msk].sum()
row('接口盒切面外露', f'{exposed:.0f} mm²', '0（科鲸外皮全包住，不露方块切面）', exposed < 5)
pm_r = res.area * 1.2 + res.volume * 0.15; pm_o = orig.area * 1.2 + orig.volume * 0.15   # 1.2 mm 外壁 + 15% 填充
row('估算打印量（外壁1.2mm+填充15%）', f'{pm_r/1000:.0f} cm³ ≈ {pm_r/1000*1.24:.0f} g（原壳 {pm_o/1000:.0f} cm³ ≈ {pm_o/1000*1.24:.0f} g，{(pm_r/pm_o-1)*100:+.0f}%）',
    '≤ 原壳 +10%', pm_r <= pm_o * 1.10)
cr, co = res.center_mass, orig.center_mass
row('重心 X/Y（前后左右）', f'({cr[0]:.1f}, {cr[1]:.1f})，原壳 ({co[0]:.1f}, {co[1]:.1f})', '偏移 ≤ 2 mm', np.linalg.norm(cr[:2] - co[:2]) <= 2.0)
row('重心高度 Z', f'{cr[2]:.1f}（原壳 {co[2]:.1f}）', '不高于原壳 +1 mm', cr[2] <= co[2] + 1.0)
# 屏幕可视率：从窗口里的点朝观众方向打光线
xs = np.arange(WIN_X[0] + 0.5, WIN_X[1], 1.0); zs = np.arange(WIN_Z[0] + 0.5, WIN_Z[1], 1.0)
P = np.array([[xx, BASE_FRONT_Y - 0.05, zz] for xx in xs for zz in zs])
vis = {}
for el in (0, 20, 35, 45):
    d = np.array([0, -np.cos(np.radians(el)), np.sin(np.radians(el))])
    hitany = res.ray.intersects_any(P, np.tile(d, (len(P), 1)))
    vis[el] = 1 - hitany.mean()
row('屏幕可视率（正视/俯20°/35°/45°）', ' / '.join(f'{vis[k]*100:.0f}%' for k in (0, 20, 35, 45)), '35° ≥ 95%', vis[35] >= 0.95)
row('旗杆（出鳍尖后）离身体最近', f'{FEAT["flag"][2]:.1f} mm', '> 3 mm（旗杆不撞头）', FEAT['flag'][2] > 3)
row('旗杆孔壁最薄处', f'{FEAT["flag_wall"]:.1f} mm', '≥ 1.2 mm（不破壁）', FEAT['flag_wall'] >= 1.2)
hp = np.array([[SMALL_HOLE[0] + dx_, BASE_FRONT_Y - 0.05, SMALL_HOLE[1] + dz_] for dx_ in (-0.5, 0, 0.5) for dz_ in (-0.5, 0, 0.5)])
hh_ = res.ray.intersects_any(hp, np.tile([0, -1.0, 0], (len(hp), 1)))
row('底座正面小孔（麦克风/传感器）', '通' if not hh_.any() else f'挡住 {hh_.sum()}/9', '正前方无遮挡', not hh_.any())
pc = (np.array([0.0, 0.0, 0.0]))
md = ['| 检查项 | 结果 | 目标 | |', '|---|---|---|---|'] + [f'| {a} | {b} | {c} | {d} |' for a, b, c, d in rows]
open(args.out.replace('.stl', '_CHECKS.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
print('\n'.join(md))

# ---------------- 上色预览（示意涂装：蓝身、白肚、黑眼、红嘴、深灰屏框） ----------------
cen = res.triangles_center
cx, cy, cz = cen[:, 0], cen[:, 1], cen[:, 2]
col = np.tile([47, 111, 189, 255], (len(cen), 1))
belly = (belly2d(cx, cz) < 0.3) & (cy < -5)
col[belly] = [243, 245, 247, 255]
cres_f = np.maximum(np.sqrt((cx - BODY_C[0]) ** 2 + (cz - c1z) ** 2) - r1, r2 - np.sqrt((cx - BODY_C[0]) ** 2 + (cz - c2z) ** 2))
col[(cres_f < 0.2) & (cy < -10)] = [200, 80, 74, 255]
for q in FEAT['eyes']:
    col[np.linalg.norm(cen - q, axis=1) < EYE['dia'] / 2 + 0.6] = [30, 38, 50, 255]
s_f = np.maximum(BASE_FRONT_Y - cy, 0)
rim = (tunnel2d(cx, cz, s_f) < RIM_W + 0.3) & (cy < BASE_FRONT_Y - 0.2)
col[rim] = [58, 66, 80, 255]
res.visual.face_colors = col
res.export(args.out.replace('.stl', '_paint.glb'))
import json
json.dump({'flag_entry': FEAT['flag'][0].tolist(), 'flag_axis': FEAT['flag'][1].tolist(), 'flag_depth': FLAG['depth'],
           'eyes': [q.tolist() for q in FEAT['eyes']], 'top_flat_z': TOP_FLAT_Z, 'body_c': BODY_C.tolist()},
          open(args.out.replace('.stl', '_features.json'), 'w'), indent=1)
print(f'total {time.time()-T0:.0f}s')
