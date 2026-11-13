"""给 v2 壳做上色示意（GLB）：按 features.json 里的 paint 列表在表面上画圆/椭圆色块。
用法：.venv/bin/python cad/paint_v2.py cad/kejing_shell_v2.stl
paint 项：name 含 belly → 椭圆（r=[rx,rz]，只涂正面）；eye → 黑色圆 + 右上角白色高光；其余 → 圆形色块。
屏框（凸沿 + 通道内壁）统一深灰。
"""
import json, sys
import numpy as np, trimesh
stl = sys.argv[1]; F = json.load(open(stl.replace('.stl', '_features.json')))
m = trimesh.load(stl); c = m.triangles_center; x, y, z = c[:, 0], c[:, 1], c[:, 2]
col = np.tile([74, 136, 214, 255], (len(c), 1))
order = sorted(F['paint'], key=lambda it: 0 if 'belly' in it['name'] else 1)
for it in order:
    p = np.array(it['p']); rgba = list(it['color']) + [255]
    if 'poly' in it:
        from matplotlib.path import Path as _P
        yf = it['y_front']
        msk = _P(np.array(it['poly'])).contains_points(c[:, [0, 2]]) & (y < yf + 5) & (y > yf - 4)
        col[msk] = rgba
        if 'highlight' in it:
            hx, hz, hr = it['highlight']
            col[(np.hypot(x - hx, z - hz) < hr) & (y < yf + 5) & (y > yf - 2)] = [255, 255, 255, 255]
        continue
    if 'belly' in it['name']:
        rx, rz = it['r']; msk = (((x - p[0]) / rx) ** 2 + ((z - p[2]) / rz) ** 2 < 1) & (y < p[1] + 18)
    else:
        msk = np.linalg.norm(c - p, axis=1) < it['r']
    col[msk] = rgba
    if 'eye' in it['name']:
        hl = p + np.array([it['r'] * 0.35, -1.0, it['r'] * 0.35]); col[np.linalg.norm(c - hl, axis=1) < it['r'] * 0.28] = [255, 255, 255, 255]
wcx = -1.61
rim = (np.abs(x - wcx) < 24.5) & (z > 1.5) & (z < 50) & (y > F['plate_front_y'] - 1.7) & (y < -27.9)
inner = rim & (y > F['plate_front_y'] + 0.4)          # 开口内壁：深色（像屏幕黑边）
col[rim & ~inner] = [246, 247, 249, 255]                # 凸沿正面：白色，并进白肚皮
col[inner] = [40, 44, 54, 255]
m.visual.face_colors = col
m.export(stl.replace('.stl', '_paint.glb')); print('wrote', stl.replace('.stl', '_paint.glb'))
