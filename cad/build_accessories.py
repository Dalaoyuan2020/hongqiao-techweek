"""科鲸配件：导游帽、小水柱、导游旗（全部原创几何，不含原版模型）。

用法：.venv/bin/python cad/build_accessories.py
帽子和水柱的底面按科鲸头顶曲面挖出来（贴合不翘），底部正中 Ø10.4×2.4 磁铁槽，
与壳顶磁铁槽对齐（Ø10×2 钕磁铁各一颗，注意极性相吸）。
旗杆 Ø3.0，插壳上右鳍 Ø3.3 斜孔。
"""
import manifold3d as mf
import numpy as np
import trimesh
from skimage import measure

# 与 build_kejing.py 保持一致
BODY_C = np.array([0.0, 2.5, 50.5]); BODY_R = np.array([45.5, 45.0, 50.5]); TOP_FLAT_Z = 100.0
MAG_R, MAG_D = 10.4 / 2, 2.4


def ellipsoid(x, y, z, c, r):
    px, py, pz = (x - c[0]) / r[0], (y - c[1]) / r[1], (z - c[2]) / r[2]
    k0 = np.sqrt(px * px + py * py + pz * pz)
    k1 = np.sqrt((px / r[0]) ** 2 + (py / r[1]) ** 2 + (pz / r[2]) ** 2)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-6)


def smin(a, b, k):
    hh = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - hh) + a * hh - k * hh * (1 - hh)


def capsule(x, y, z, a, b, ra, rb):
    a, b = np.asarray(a, float), np.asarray(b, float); ab = b - a
    t = np.clip(((x - a[0]) * ab[0] + (y - a[1]) * ab[1] + (z - a[2]) * ab[2]) / (ab @ ab), 0, 1)
    return np.sqrt((x - a[0] - t * ab[0]) ** 2 + (y - a[1] - t * ab[1]) ** 2 + (z - a[2] - t * ab[2]) ** 2) - (ra + (rb - ra) * t)


def mesh_from_sdf(fn, lo, hi, h=0.25):
    g = [np.arange(l, u + h, h, dtype=np.float32) for l, u in zip(lo, hi)]
    D = fn(g[0][:, None, None], g[1][None, :, None], g[2][None, None, :])
    assert min(D[0].min(), D[-1].min(), D[:, 0].min(), D[:, -1].min(), D[:, :, 0].min(), D[:, :, -1].min()) > 0
    v, f, _, _ = measure.marching_cubes(D, 0.0, spacing=(h, h, h))
    m = trimesh.Trimesh(v + np.array([g[0][0], g[1][0], g[2][0]]), f, process=False)
    if m.volume < 0:
        m.invert()
    man = mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
    assert man.status() == mf.Error.NoError, man.status()
    mm = man.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)


def seat(d, x, y, z):
    """挖掉头顶（局部坐标：z=0 为壳顶平台，xy 原点为平台中心）+ 磁铁槽"""
    head = np.maximum(ellipsoid(x, y, z, (0, 0, BODY_C[2] - TOP_FLAT_Z), BODY_R + 0.4), z)   # 弧面留 0.4 mm 间隙，只靠平台+磁铁落座，不晃
    d = np.maximum(d, -head)
    pocket = np.maximum(np.sqrt(x * x + y * y) - MAG_R, np.maximum(-z - 1, z - MAG_D))
    return np.maximum(d, -pocket)


def hat(x, y, z):
    dome = ellipsoid(x, y, z, (0, 0, 1.5), (17.0, 17.0, 13.0))
    band = ellipsoid(x, y, z, (0, 0, 2.0), (17.8, 17.8, 4.2))
    visor = ellipsoid(x, y, z, (0, -15.0, 1.6), (14.0, 13.0, 2.0))
    knob = ellipsoid(x, y, z, (0, 0, 14.0), (2.6, 2.6, 2.2))
    d = smin(smin(dome, band, 1.0), visor, 2.0)
    d = smin(d, knob, 1.0)
    d = np.maximum(d, -2.5 - z)   # 帽檐下沿不往下垂太多
    return seat(d, x, y, z)


def spout(x, y, z):
    base = ellipsoid(x, y, z, (0, 0, 0.5), (8.5, 8.5, 4.0))
    d = smin(base, capsule(x, y, z, (0, 0, 1), (0, 0, 15), 3.4, 2.3), 2.0)
    for sx in (-1, 1):
        d = smin(d, capsule(x, y, z, (0, 0, 9), (sx * 7.5, 0, 17.5), 2.4, 1.9), 1.6)
        d = smin(d, ellipsoid(x, y, z, (sx * 9.5, 0, 19.5), (2.6, 2.6, 2.6)), 1.2)
    d = smin(d, ellipsoid(x, y, z, (0, 0, 18.0), (3.0, 3.0, 3.0)), 1.2)
    for sy in (-1, 1):
        d = smin(d, capsule(x, y, z, (0, 0, 8), (0, sy * 6.5, 14.5), 2.0, 1.7), 1.4)
    d = np.maximum(d, -2.0 - z)
    return seat(d, x, y, z)


def flag():
    """平躺打印：旗面贴床，旗杆 Ø3 也贴床。杆长 75，插孔深 12。"""
    pole = mf.Manifold.cylinder(75.0, 1.5, 1.5, 48).rotate([0, 90, 0]).translate([0, 0, 1.5])
    pennant = mf.CrossSection([[(52.0, 0.0), (75.0, 0.0), (75.0, 24.0), (52.0, 24.0)]]).extrude(1.6)
    tri = mf.CrossSection([[(75.0, 0.0), (92.0, 12.0), (75.0, 24.0)]]).extrude(1.6)
    tip = mf.Manifold.sphere(2.4, 32).translate([-1.0, 0, 2.4])
    return pole + pennant + tri + tip


out = {}
out['guide_hat'] = mesh_from_sdf(hat, (-22, -32, -8), (22, 22, 20))
out['water_spout'] = mesh_from_sdf(spout, (-16, -12, -8), (16, 12, 26))
fm = flag().to_mesh()
out['guide_flag'] = trimesh.Trimesh(np.asarray(fm.vert_properties)[:, :3], np.asarray(fm.tri_verts))
for k, m in out.items():
    parts = m.split(only_watertight=False); m = max(parts, key=lambda p: p.volume)
    m.export(f'cad/{k}.stl')
    print(f'{k}: watertight {m.is_watertight}, bodies {len(parts)}, size {np.round(m.extents, 1).tolist()} mm, vol {m.volume/1000:.1f} cm3')
