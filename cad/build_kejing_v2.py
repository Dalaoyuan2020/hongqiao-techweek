"""科鲸壳 v2 生成脚本：造型区用 AI 图转 3D 的网格（混元 3D），接口区从原壳网格精确保留。

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
ap.add_argument('--out', default='cad/kejing_shell_v2.stl')
ap.add_argument('--ai', required=True, help='混元 3D 输出 glb')
ap.add_argument('--landmarks', required=True, help='AI 网格上的屏框/身体底部位置 json')
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

# ---------------- v2 参数 ----------------
SKIRT = ((-48.0, 44.8), (-36.5, 48.0), (-6.5, 46.5)); SKIRT_RAD = 18.0; SKIRT_ZRAD = 8.0; SKIRT_K = 14.0   # 兜底接口盒
BODY_C = np.array([0.0, 2.5, 50.5]); TOP_FLAT_Z = 999.0
FLAG = dict(dia=3.3, depth=12.0, x=-24.0, y=16.0)
TUNNEL_MARGIN = 1.0; TUNNEL_MARGIN_X = 5.3; TUNNEL_CORNER = 4.0; FLARE_SIDE = 0.25
FLARE_TOP = 0.8; FLARE_BOT = 0.35
RIM_W = 3.0; RIM_UP = 1.3

h = args.res
gx = np.arange(-75, 75 + h, h, dtype=np.float32)
gy = np.arange(-70, 85 + h, h, dtype=np.float32)
gz = np.arange(-9, 150 + h, h, dtype=np.float32)
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



import igl
import json
from scipy import ndimage
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import map_coordinates

ORIGIN = np.array([gx[0], gy[0], gz[0]])
LM = json.load(open(args.landmarks, encoding='utf-8'))
S = LM['scale']; wcx = (WIN_X[0] + WIN_X[1]) / 2; wcz = (WIN_Z[0] + WIN_Z[1]) / 2


def sample(D, pts):
    pts = np.atleast_2d(np.asarray(pts, float))
    return map_coordinates(D, ((pts - ORIGIN) / h).T, order=1, mode='nearest')


def capsule_r(x, y, z, a, b, ra, rb):
    a = np.asarray(a, float); b = np.asarray(b, float); ab = b - a
    t = np.clip(((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / (ab @ ab), 0, 1)
    return np.sqrt((x - a[0] - t * ab[0]) ** 2 + (y - a[1] - t * ab[1]) ** 2 + (z - a[2] - t * ab[2]) ** 2) - (ra + (rb - ra) * t)


def hit(D, p_out, d):
    d = np.asarray(d, float); d /= np.linalg.norm(d)
    ts = np.arange(0, 120, 0.1); pts = np.asarray(p_out, float) + ts[:, None] * d
    v = sample(D, pts); i = int(np.argmax(v < 0)); assert v[i] < 0, ('miss', p_out, d)
    return pts[i]


FEAT = {}

# ---------- 1 读 AI 网格（混元 3D 输出：Y 朝上、正面 +Z）→ 我们的坐标（Z 朝上、正面 -Y） ----------
ai = trimesh.load(args.ai)
ai = ai.to_geometry() if isinstance(ai, trimesh.Scene) else ai
ai.merge_vertices(digits_vertex=5)
ai.apply_transform(np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1.0]]))
if LM.get('yaw_deg'):
    ai.apply_transform(trimesh.transformations.rotation_matrix(np.radians(LM['yaw_deg']), [0, 0, 1], [LM['screen_cx'], 0, 0]))
V = np.asarray(ai.vertices, float); Fc = np.asarray(ai.faces, np.int64)

# 屏框正面的 y（AI 单位）：取屏框外框范围内最靠前的表面
fx0, fx1, fz0, fz1 = LM['frame']
q = np.stack(np.meshgrid(np.linspace(fx0, fx1, 40), np.linspace(-1.2, 1.2, 480), np.linspace(fz0, fz1, 40), indexing='ij'), -1).reshape(-1, 3)
wq = igl.fast_winding_number(V, Fc, q).reshape(40, 480, 40) > 0.5
first = np.where(wq.any(1), wq.argmax(1), 479)
frame_front_y = float(np.percentile(np.linspace(-1.2, 1.2, 480)[first], 10))
print('AI frame front y =', round(frame_front_y, 3))

# ---------- 2 坐标映射：x/y 等比；z 用单调样条（屏框以下压缩，让屏幕落到底座窗口高度） ----------
zb, zfb, zsc = LM['body_bottom_z'], fz0, LM['screen_cz']
Z_fb = wcz - (zsc - zfb) * S
s_low = Z_fb / (zfb - zb)
knots_Z = [-30.0, 0.0, Z_fb, wcz, 300.0]
KZU = LM.get('scale_z_upper', 1.0)               # 屏幕以上（脸和头）竖向拉高系数
knots_z = [zb - 30.0 / s_low, zb, zfb, zsc, zsc + (300.0 - wcz) / (S * KZU)]
zmap = PchipInterpolator(knots_Z, knots_z)
print(f'scale {S} mm/unit, lower body compressed to {s_low:.1f} mm/unit (frame bottom at Z={Z_fb:.1f})')
SY = LM.get('scale_y', 1.0)                     # 前后方向压扁系数（AI 身体偏深）
TX0, TK = LM.get('tail_x0', 999.0), LM.get('tail_k', 1.0)   # X > TX0 的部分（侧后方尾巴）往身体收


xg = gx.astype(float); dxg = np.diff(xg, prepend=xg[0])
w_ = np.clip((xg - TX0) / 6.0, 0, 1); slope = 1 + (1 / TK - 1) * w_ * w_ * (3 - 2 * w_)
xp = xg[0] + np.cumsum(slope * dxg)              # 积分得到单调、光滑的反映射
xa = (xp - wcx) / S + LM['screen_cx']
ya = (gy - LM['plate_front_y_mm']) / (S * SY) + frame_front_y
za = zmap(gz)

# ---------- 3 占据场：卷绕数 > 0.5 即在体内（AI 网格不水密也没关系） ----------
occ = np.zeros((len(gx), len(gy), len(gz)), bool)
for k0 in range(0, len(gz), 40):
    zz = za[k0:k0 + 40]
    Q = np.stack(np.meshgrid(xa, ya, zz, indexing='ij'), -1).reshape(-1, 3)
    occ[:, :, k0:k0 + 40] = (igl.fast_winding_number(V, Fc, Q) > 0.5).reshape(len(gx), len(gy), len(zz))
occ[:, :, gz < -3.0] = False                                   # 腿去掉（Z<0 之后还会整体切平）
print(f'occupancy done {time.time()-T0:.0f}s')

# ---------- 4 有符号距离场（mm）：先用体素距离粗算，再在表面 ±3 mm 带内用 KD 树算到 AI 表面的精确距离 ----------
from scipy.spatial import cKDTree
D = (ndimage.distance_transform_edt(~occ) - ndimage.distance_transform_edt(occ)).astype(np.float32) * h
pts_ai, _ = trimesh.sample.sample_surface(trimesh.Trimesh(V, Fc, process=False), 3_000_000, seed=1)
inv_z = PchipInterpolator(knots_z, knots_Z)
Xr = np.interp((pts_ai[:, 0] - LM['screen_cx']) * S + wcx, xp, gx)
Yr = (pts_ai[:, 1] - frame_front_y) * S * SY + LM['plate_front_y_mm']
Zr = inv_z(pts_ai[:, 2])
tree = cKDTree(np.c_[Xr, Yr, Zr])
band = np.argwhere(np.abs(D) < 3.0)
dist, _ = tree.query(np.c_[gx[band[:, 0]], gy[band[:, 1]], gz[band[:, 2]]], workers=-1)
D[band[:, 0], band[:, 1], band[:, 2]] = (np.sign(D[band[:, 0], band[:, 1], band[:, 2]]) * dist).astype(np.float32)
D = ndimage.gaussian_filter(D, 0.5)
del occ
print(f'exact SDF band {len(band)/1e6:.1f}M voxels, {time.time()-T0:.0f}s')
sl, x, y, z = sub(((-80, 80), (-80, 90), (-12, 2)))
D[sl] = np.maximum(D[sl], -3.0 - z)                             # 腿切平（Z<0 之后整体再切）
# 屏幕平板：把 AI 的屏框凹槽换成一块平整的板（真屏幕窗口下面按实物开）
px0 = np.interp((fx0 - LM['screen_cx']) * S + wcx, xp, gx); px1 = np.interp((fx1 - LM['screen_cx']) * S + wcx, xp, gx)
pz0, pz1 = float(inv_z(fz0)), float(inv_z(fz1))
sl, x, y, z = sub(((px0 - 5, px1 + 5), (LM['plate_front_y_mm'] - 5, LM['plate_front_y_mm'] + 30), (pz0 - 5, pz1 + 5)))
plate = round_box(x, y, z, ((px0, px1), (LM['plate_front_y_mm'], LM['plate_front_y_mm'] + 25), (pz0, pz1)), 3.0)
D[sl] = np.minimum(D[sl], plate)

# ---------- 4b 换尾巴：AI 尾巴是贴上去的薄片（像叶子），切掉后重建一条圆润的小尾巴 ----------
TL = LM.get('tail_replace')
if TL:
    # 1) 用背部表面拟合一个椭球（不含尾巴、脸、水柱），作为切尾巴后的光滑背面
    nz_ = np.argwhere(np.abs(D) < 0.35)
    P_ = np.c_[gx[nz_[:, 0]], gy[nz_[:, 1]], gz[nz_[:, 2]]].astype(float)
    sel_ = (P_[:, 2] > 50) & (P_[:, 2] < 96) & (P_[:, 1] > -10) & ~((P_[:, 0] > TL['cut_x'] - 4) & (P_[:, 2] > TL['cut_z'] - 4))
    P_ = P_[sel_]
    A_ = np.c_[P_ ** 2, P_]
    co_ = np.linalg.lstsq(A_, np.ones(len(P_)), rcond=None)[0]
    a2, d1 = co_[:3], co_[3:]
    ec = -d1 / (2 * a2); rhs = 1 + np.sum(d1 ** 2 / (4 * a2)); er = np.sqrt(rhs / a2)
    print('dome fit center', np.round(ec, 1), 'radii', np.round(er, 1))
    sl, x, y, z = sub(((TL['cut_x'] - 6, 80), (-50, 80), (TL['cut_z'] - 6, 140)))
    w_ = np.clip((x - TL['cut_x']) / 5.0, 0, 1) * np.clip((z - TL['cut_z']) / 5.0, 0, 1) * np.clip((y - TL.get('cut_y', -5.0)) / 5.0, 0, 1)
    spout_ = (np.abs(x - TL.get('spout_x', 0.0)) < 16) & (z > TL.get('spout_z', 94.0))      # 水柱不动
    w_ = np.where(spout_, 0.0, w_)
    trimmed = np.maximum(D[sl], ellipsoid(x, y, z, ec, er) - TL.get('margin', 1.2))
    D[sl] = D[sl] + w_ * (trimmed - D[sl])
    # 2) 新尾巴：从后背下方长出来的粗尾柄（向后上方弯），末端两片圆润的尾鳍
    root = hit(D, [TL['root_x'], gy[-1] - 2, TL['root_z']], [0, -1, 0])
    chain = [root + np.array(TL['p0']), root + np.array(TL['p1']), root + np.array(TL['p2'])]
    radii = TL['radii']
    lo_ = np.min(chain, 0) - 30; hi_ = np.max(chain, 0) + 30
    sl, x, y, z = sub(tuple(zip(lo_, hi_)))
    tail = None
    for i in range(len(chain) - 1):
        seg = capsule_r(x, y, z, chain[i], chain[i + 1], radii[i], radii[i + 1])
        tail = seg if tail is None else smin(tail, seg, 3.0)
    tip = chain[-1]
    for sx_ in (-1, 1):
        ang = np.radians(TL['lobe_tilt'])
        u_ = np.array([sx_ * np.cos(ang), 0.0, np.sin(ang)]); v_ = np.array([0.0, 1.0, 0.0]); w2 = np.cross(u_, v_)
        lc = tip + np.array([sx_ * TL['lobe_dx'], TL['lobe_dy'], TL['lobe_dz']])
        tail = smin(tail, oriented_ellipsoid(x, y, z, lc, (u_, v_, w2), TL['lobe_r']), 4.0)
    D[sl] = smin(D[sl], tail, TL.get('blend', 7.0))
    FEAT['tail'] = {'root': root.tolist(), 'tip': tip.tolist()}
    print('new tail root', np.round(root, 1), 'tip', np.round(tip, 1))

# ---------- 4c 重做嘴：AI 的嘴只是一个圆鼓包加两个小坑（像鼻子），磨平后刻一张真正的嘴 ----------
MO = LM.get('mouth')
if MO:
    mx0, mx1, mz0, mz1 = MO['smooth_box']            # 磨平区域（避开眼睛和屏框）
    sl, x, y, z = sub(((mx0 - 6, mx1 + 6), (-70, 0), (mz0 - 6, mz1 + 6)))
    Ds = ndimage.gaussian_filter(D[sl], MO.get('smooth_sigma', 2.5) / h)
    w_ = (np.clip((x - mx0) / 2.0, 0, 1) * np.clip((mx1 - x) / 2.0, 0, 1) * np.clip((z - mz0) / 2.0, 0, 1) * np.clip((mz1 - z) / 2.0, 0, 1)) * (y < 0)
    D[sl] = D[sl] + w_ * (Ds - D[sl])
    Dface = D[sl].copy()
    cx, zt = MO['cx'], MO['zt']
    def mouth2d(xx, zz):
        if MO['style'] == 'arc':                       # 一道微笑弧线（两个圆之间的月牙）
            r1, r2, off = MO['r1'], MO['r2'], MO['arc_off']
            c1z, c2z = zt + r1, zt + off + r2
            return np.maximum(np.sqrt((xx - cx) ** 2 + (zz - c1z) ** 2) - r1, r2 - np.sqrt((xx - cx) ** 2 + (zz - c2z) ** 2))
        rx, rz = MO['rx'], MO['rz']                    # D 形开口笑：下半椭圆 + 两角微微上翘的上沿
        ell = (np.sqrt(((xx - cx) / rx) ** 2 + ((zz - zt) / rz) ** 2) - 1) * min(rx, rz)
        top = zz - (zt + MO.get('smile', 0.05) * (xx - cx) ** 2)
        return np.maximum(ell, top) - 0.0
    m2 = mouth2d(x, z)
    carve = np.maximum(np.maximum(m2, -(Dface + MO['depth'])), y - 0.0)
    D[sl] = np.maximum(D[sl], -carve)
    if MO.get('tongue'):
        tdx, tdz, trx, trz = MO['tongue']
        t2 = (np.sqrt(((x - cx - tdx) / trx) ** 2 + ((z - zt - tdz) / trz) ** 2) - 1) * min(trx, trz)
        t2 = np.maximum(t2, m2 + 0.5)                  # 舌头在嘴里面，离嘴边留 0.5 mm
        D[sl] = np.minimum(D[sl], np.maximum(np.maximum(t2, Dface + MO['tongue_drop']), y - 0.0))
    # 上色用的精确轮廓（不再靠识别）
    import matplotlib; matplotlib.use('Agg')
    from skimage import measure as _ms
    gx2 = np.arange(cx - 20, cx + 20, 0.1); gz2 = np.arange(zt - 15, zt + 15, 0.1)
    XX, ZZ = np.meshgrid(gx2, gz2, indexing='ij')
    def _poly(field):
        cs_ = _ms.find_contours(field, 0.0); c_ = max(cs_, key=len)
        return np.c_[gx2[0] + c_[:, 0] * 0.1, gz2[0] + c_[:, 1] * 0.1][::2]
    yf = float(hit(D, [cx, gy[0] + 2, zt - 2.0], [0, 1, 0])[1])      # 在嘴自身位置取前表面
    FEAT['mouth_paint'] = [{'name': 'mouth', 'poly': _poly(mouth2d(XX, ZZ)).round(3).tolist(), 'y_front': yf, 'fixed': True,
                            'color': MO.get('color', [30, 34, 42]), 'p': [cx, yf, zt - 2], 'r': 5.0}]
    if MO.get('tongue'):
        tdx, tdz, trx, trz = MO['tongue']
        tf = np.maximum((np.sqrt(((XX - cx - tdx) / trx) ** 2 + ((ZZ - zt - tdz) / trz) ** 2) - 1) * min(trx, trz), mouth2d(XX, ZZ) + 0.5)
        yft = float(hit(D, [cx + tdx, gy[0] + 2, zt + tdz], [0, 1, 0])[1])
        FEAT['mouth_paint'].append({'name': 'tongue', 'poly': _poly(tf).round(3).tolist(), 'y_front': yft, 'fixed': True,
                                    'color': [240, 138, 154], 'p': [cx + tdx, yf, zt + tdz], 'r': 3.0})
    print('mouth', MO['style'], 'front y', round(yf, 1))

# ---------- 5 裙边保底：保证从底面到顶板都包住接口盒（AI 身体下半截偏窄时补齐） ----------
m = SKIRT_K + 1
sl, x, y, z = sub(((SKIRT[0][0] - m, SKIRT[0][1] + m), (SKIRT[1][0] - m, SKIRT[1][1] + m), (SKIRT[2][0] - m, SKIRT[2][1] + m)))
D[sl] = smin(D[sl], round_prism(x, y, z, SKIRT, SKIRT_RAD, SKIRT_ZRAD), SKIRT_K)

FEAT.setdefault('eyes', [])
EYE = dict(dia=LM.get('eye_dia_mm', 7.0))
c1z, r1, c2z, r2 = LM.get('crescent', [-999.0, 1.0, -999.0, 1.0])   # 白色月牙笑弧（上色示意）：圆1内、圆2外
FEAT['paint'] = []
zinv_ = PchipInterpolator(knots_z, knots_Z)
for item in LM.get('paint', []):          # [名称, AI x, AI z, 半径或[rx,rz] mm, 颜色 RGB]
    name_, ax_, az_, r_, col_ = item
    Xp = float(np.interp((ax_ - LM['screen_cx']) * S + wcx, xp, gx)); Zp = float(zinv_(az_))
    q_ = hit(D, [Xp, gy[0] + 2, Zp], [0, 1, 0])
    if name_ == 'mouth' and 'mouth_paint' in FEAT:
        continue
    FEAT['paint'].append({'name': name_, 'p': q_.tolist(), 'r': r_, 'color': col_})
FEAT['paint'] += FEAT.get('mouth_paint', [])
for ex_, ez_ in LM.get('eyes', []):
    Xe = float(np.interp((ex_ - LM['screen_cx']) * S + wcx, xp, gx)); Ze = float(PchipInterpolator(knots_z, knots_Z)(ez_))
    FEAT['eyes'].append(hit(D, [Xe, gy[0] + 2, Ze], [0, 1, 0]))


def belly2d(x, z):
    return np.full(np.shape(x), 1e9)


# ---------- 6 屏框：圆角方口外张 + 凸沿（与 v1 相同，按实物窗口开） ----------
whx = (WIN_X[1] - WIN_X[0]) / 2 + TUNNEL_MARGIN_X


def tunnel2d(x, z, s):
    s = np.maximum(s, 0)
    return round_rect2(x - wcx, z, whx + FLARE_SIDE * s, whx + FLARE_SIDE * s,
                       -(WIN_Z[0] - TUNNEL_MARGIN - FLARE_BOT * s), WIN_Z[1] + TUNNEL_MARGIN + FLARE_TOP * s, TUNNEL_CORNER)


assert wcx + whx >= SMALL_HOLE[0] + 1.3
sl, x, y, z = sub(((-50, 47), (-64, -20), (-9, 72)))
ring = np.abs(tunnel2d(x, z, BASE_FRONT_Y - y) - RIM_W / 2) - RIM_W / 2
D[sl] = np.minimum(D[sl], np.maximum(np.maximum(ring, D[sl] - RIM_UP), y - (BASE_FRONT_Y - 0.4)))
D[sl] = np.maximum(D[sl], -np.maximum(tunnel2d(x, z, BASE_FRONT_Y - y), y - (BASE_FRONT_Y + 0.2)))

# ---------- 7 导游旗插孔：头顶后侧（机器人右后方）竖直 Ø3.3 深 12，像导游背包上的小旗 ----------
axis = np.array([0.0, 0.0, 1.0])
P0 = hit(D, [FLAG['x'], FLAG['y'], 160.0], -axis)
e1 = np.cross(axis, [1.0, 0, 0]); e1 /= np.linalg.norm(e1); e2 = np.cross(axis, e1)
walls = []
for tt in np.arange(2.5, FLAG['depth'] + 0.01, 0.5):
    for ang in np.radians(np.arange(0, 360, 30)):
        dirr = np.cos(ang) * e1 + np.sin(ang) * e2
        probe = P0 - axis * tt + (FLAG['dia'] / 2 + np.arange(0, 6.01, 0.1))[:, None] * dirr
        out_ = np.nonzero(sample(D, probe) > 0)[0]
        walls.append(out_[0] * 0.1 if len(out_) else 6.0)
bot = sample(D, P0 - axis * (FLAG['depth'] + 1.2))[0]
FEAT['flag_wall'] = float(min(min(walls), 6.0 if bot < 0 else 0.0))
sl, x, y, z = sub(((P0[0] - 6, P0[0] + 6), (P0[1] - 30, P0[1] + 10), (P0[2] - 16, P0[2] + 40)))
dx, dy, dz = x - P0[0], y - P0[1], z - P0[2]
t = dx * axis[0] + dy * axis[1] + dz * axis[2]
rr = np.sqrt(np.maximum((dx - t * axis[0]) ** 2 + (dy - t * axis[1]) ** 2 + (dz - t * axis[2]) ** 2, 0))
D[sl] = np.maximum(D[sl], -np.maximum(rr - FLAG['dia'] / 2, -(t + FLAG['depth'])))
line = P0 + np.arange(12, 80, 1.0)[:, None] * axis
FEAT['flag'] = (P0, axis, float(sample(D, line).min()))
print('flag hole entry', np.round(P0, 1), 'clearance', round(FEAT['flag'][2], 1), 'wall', round(FEAT['flag_wall'], 1))

assert D[0].min() > 0 and D[-1].min() > 0 and D[:, 0].min() > 0 and D[:, -1].min() > 0 and D[:, :, -1].min() > 0 and D[:, :, 0].min() > 0, "SDF touches grid boundary"
print(f'sdf done {time.time()-T0:.0f}s')

verts, faces, _, _ = measure.marching_cubes(D, level=0.0, spacing=(h, h, h))
verts += np.array([gx[0], gy[0], gz[0]])
D_keep = D
W = trimesh.Trimesh(verts, faces, process=True)
if W.volume < 0:
    W.invert()
print(f'marching cubes: {len(W.faces)} faces, watertight={W.is_watertight}, {time.time()-T0:.0f}s')


def W_sdf_sample(pts):
    return map_coordinates(D_keep, ((np.asarray(pts) - ORIGIN) / h).T, order=1, mode='nearest')


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
# 腔体顶改 45° 斜顶（四坡屋顶）：原来 70×70 的平顶打印时整个腔体要填支撑，斜顶自支撑。
# 前沿留 ROOF_FRONT_STRIP mm 平顶，继续压住电路板上沿（官方要求「外壳前侧压住电路板」）。
ROOF_FRONT_STRIP = 6.0
rx0, rx1 = CAV_X; ry0, ry1 = BASE_FRONT_Y + ROOF_FRONT_STRIP, CAV_Y_BACK; rz0 = CAV_TOP - 0.05
half = min(rx1 - rx0, ry1 - ry0) / 2
if (rx1 - rx0) >= (ry1 - ry0):
    ridge = [[rx0 + half, (ry0 + ry1) / 2, rz0 + half], [rx1 - half, (ry0 + ry1) / 2, rz0 + half]]
else:
    ridge = [[(rx0 + rx1) / 2, ry0 + half, rz0 + half], [(rx0 + rx1) / 2, ry1 - half, rz0 + half]]
roof_pts = [[rx0, ry0, rz0], [rx1, ry0, rz0], [rx0, ry1, rz0], [rx1, ry1, rz0]] + ridge
roof = mf.Manifold.hull_points(roof_pts)
roof_pts_np = np.array(roof_pts)
# 斜顶离外表面的最小壁厚：在屋顶面上密采样，查造型距离场
_sm = trimesh.Trimesh(*[np.asarray(a_) for a_ in (lambda mm: (mm.vert_properties[:, :3], mm.tri_verts))(roof.to_mesh())], process=False)
_pts, _ = trimesh.sample.sample_surface(_sm, 20000, seed=2)
_pts = _pts[_pts[:, 2] > CAV_TOP + 0.5]
ROOF_WALL = float(-W_sdf_sample(_pts).max()) if len(_pts) else 99.0
# 腔体入口内沿 0.8 mm×45° 倒角：防第一层「象脚」外扩后扣不进底座
CH = 0.8
cx0, cx1 = CAV_X
chamfer = mf.Manifold.hull_points([[cx0 - CH - 1, KEEP_BOX[1][0] - 1, -1.0], [cx1 + CH + 1, KEEP_BOX[1][0] - 1, -1.0],
                                   [cx0 - CH - 1, CAV_Y_BACK + CH + 1, -1.0], [cx1 + CH + 1, CAV_Y_BACK + CH + 1, -1.0],
                                   [cx0, KEEP_BOX[1][0] - 1, CH], [cx1, KEEP_BOX[1][0] - 1, CH],
                                   [cx0, CAV_Y_BACK, CH], [cx1, CAV_Y_BACK, CH]])
E = (kbox - O) + (pin_void - O) + head_void + zneg + roof + chamfer
K = ((O ^ kbox) - roof - chamfer) + (O ^ pin_keep)
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
kz = kbox - roof - chamfer   # v2：只比接口盒；斜顶和入口倒角是有意改的
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
def _ridge_thickness(b):
    """区域内实体沿「中脊」的厚度（内切球直径），取第 10 百分位；避开盒子边界 1 mm"""
    sl_, x_, y_, z_ = sub(b)
    occ_ = D_keep[sl_] < 0
    edt = ndimage.distance_transform_edt(occ_) * h
    ridge_ = occ_ & (edt >= ndimage.maximum_filter(edt, size=3) - 1e-6) & (edt > h)
    m_ = int(round(1.0 / h)); ridge_[:m_] = ridge_[-m_:] = False; ridge_[:, :m_] = ridge_[:, -m_:] = False; ridge_[:, :, :m_] = ridge_[:, :, -m_:] = False
    t_ = 2 * edt[ridge_]
    return float(np.percentile(t_, 10)) if len(t_) else 99.0
TH_SPOUT = _ridge_thickness(((-25, 25), (-25, 30), (98, 140)))
TH_TAIL = _ridge_thickness(((FEAT['tail']['tip'][0] - 30, FEAT['tail']['tip'][0] + 30), (FEAT['tail']['root'][1] + 4, 90), (55, 140))) if 'tail' in FEAT else _ridge_thickness(((10, 70), (-5, 45), (70, 140)))
row('细部厚度（水柱 / 尾巴，中脊第10百分位）', f'{TH_SPOUT:.1f} / {TH_TAIL:.1f} mm', '≥ 2.5 mm（打印不易断）', min(TH_SPOUT, TH_TAIL) >= 2.5)
row('腔体入口倒角', f'{CH} mm × 45°', '防第一层象脚扣不进', True)
row('腔体斜顶（免内部支撑）', f'坡顶 45°，前沿 {ROOF_FRONT_STRIP:.0f} mm 平顶压板，顶点 Z={roof_pts_np[:, 2].max():.0f}', '斜顶离外表面 ≥ 3 mm', ROOF_WALL >= 3.0)
row('斜顶处最薄壁厚', f'{ROOF_WALL:.1f} mm', '≥ 3 mm', ROOF_WALL >= 3.0)
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
col[(cres_f < 0.2) & (cy < -10)] = [246, 247, 249, 255]   # v2：白色月牙
for q in FEAT['eyes']:
    col[np.linalg.norm(cen - q, axis=1) < EYE['dia'] / 2 + 0.6] = [30, 38, 50, 255]
s_f = np.maximum(BASE_FRONT_Y - cy, 0)
rim = (tunnel2d(cx, cz, s_f) < RIM_W + 0.3) & (cy < BASE_FRONT_Y - 0.2)
col[rim] = [58, 66, 80, 255]
res.visual.face_colors = col
res.export(args.out.replace('.stl', '_paint.glb'))
import json
json.dump({'flag_entry': FEAT['flag'][0].tolist(), 'flag_axis': FEAT['flag'][1].tolist(), 'flag_depth': FLAG['depth'],
           'scale': S, 'paint': FEAT.get('paint', []), 'plate_front_y': LM['plate_front_y_mm']},
          open(args.out.replace('.stl', '_features.json'), 'w'), indent=1)
print(f'total {time.time()-T0:.0f}s')
