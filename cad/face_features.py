"""从壳的实际几何里找出脸部特征（眼睛、腮红、嘴）的真实轮廓，写回 features.json，
让上色、拆色、描边槽都和建模对齐（不再用手估的圆）。

用法：.venv/bin/python cad/face_features.py cad/kejing_shell_v2e.stl
做法：从正面算一张深度图 → 减去 3 mm 高斯平滑的底面 → 剩下的「浮雕」里，凸起处
（残差 < -0.15 mm）就是眼睛/腮红/嘴。以 features.json 里原来的大概位置为种子，
取最近的凸起块，提取它的轮廓多边形（mm 坐标，X–Z 平面）。
"""
import json
import sys

import igl
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure

stl = sys.argv[1]
fj = stl.replace('.stl', '_features.json')
F = json.load(open(fj, encoding='utf-8'))
r = trimesh.load(stl); V = np.asarray(r.vertices, float); Fc = np.asarray(r.faces, np.int64)
h = 0.25
xs = np.arange(-50, 50, h); zs = np.arange(30, 100, h); ys = np.arange(-55, -12, h)
X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
w = igl.fast_winding_number(V, Fc, np.c_[X.ravel(), Y.ravel(), Z.ravel()]).reshape(X.shape)
occ = w > 0.5
anyy = occ.any(1); k = occ.argmax(1); k0 = np.clip(k - 1, 0, len(ys) - 1)
w0 = np.take_along_axis(w, k0[:, None, :], 1)[:, 0]; w1 = np.take_along_axis(w, k[:, None, :], 1)[:, 0]
depth = ys[0] + (k0 + np.clip((0.5 - w0) / np.maximum(w1 - w0, 1e-6), 0, 1)) * h
depth[~anyy] = np.nan
res = depth - ndimage.gaussian_filter(np.nan_to_num(depth, nan=np.nanmax(depth)), 12)
inner = ndimage.binary_erosion(anyy, iterations=int(4 / h))
Xg, Zg = np.meshgrid(xs, zs, indexing='ij')
raised = inner & (res < -0.15) & (Zg > 49.5)
lab, n = ndimage.label(raised)
cents = ndimage.center_of_mass(raised, lab, range(1, n + 1))
areas = ndimage.sum(raised, lab, range(1, n + 1)) * h * h

report = []
for it in F['paint']:
    if it['name'].startswith('belly') or it.get('fixed'):
        continue
    sx, sz = it['p'][0], it['p'][2]
    best, bd = None, 1e9
    for i, (c, a) in enumerate(zip(cents, areas)):
        if a < 8:
            continue
        cx, cz = xs[0] + c[0] * h, zs[0] + c[1] * h
        dd = np.hypot(cx - sx, cz - sz)
        if dd < bd:
            best, bd = i + 1, dd
    if best is None or bd > 10:
        report.append(f"{it['name']}: 没找到对应凸起（最近 {bd:.1f} mm），保留原位置")
        continue
    m = ndimage.binary_fill_holes(lab == best)
    m = ndimage.binary_opening(m, iterations=1)
    cs = measure.find_contours(np.pad(m, 1).astype(float), 0.5)
    cmax = max(cs, key=len)[::2] - 1
    poly = np.c_[xs[0] + cmax[:, 0] * h, zs[0] + cmax[:, 1] * h]
    cx, cz = Xg[m].mean(), Zg[m].mean()
    yi = np.nanmin(depth[m])
    old = (sx, sz)
    it['poly'] = np.round(poly, 3).tolist()
    it['p'] = [float(cx), float(np.nanmean(depth[m])), float(cz)]
    it['y_front'] = float(yi)
    wbox, hbox = np.ptp(poly[:, 0]), np.ptp(poly[:, 1])
    if it['name'].startswith('eye'):
        it['highlight'] = [float(cx + 0.22 * wbox), float(cz + 0.22 * hbox), float(0.17 * min(wbox, hbox))]
    report.append(f"{it['name']}: 原来 ({old[0]:.1f}, {old[1]:.1f}) → 实际 ({cx:.1f}, {cz:.1f})，偏了 {np.hypot(cx-old[0], cz-old[1]):.1f} mm；轮廓 {wbox:.1f}×{hbox:.1f} mm")
json.dump(F, open(fj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
np.savez_compressed(stl.replace('.stl', '_facerelief.npz'), res=res, xs=xs, zs=zs)
print('\n'.join(report))
