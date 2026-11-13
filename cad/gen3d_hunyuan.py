"""概念图 → 3D 网格（Hugging Face 上的腾讯混元 3D-2 Space，ZeroGPU 免费额度）。
用法：.venv/bin/python cad/gen3d_hunyuan.py <image.png> <out.glb> [--space tencent/Hunyuan3D-2]
需要环境变量 HF_ALL（或 HF_TOKEN）。
"""
import os, shutil, sys, time, argparse
from gradio_client import Client, handle_file
ap = argparse.ArgumentParser(); ap.add_argument('image'); ap.add_argument('out'); ap.add_argument('--space', default='tencent/Hunyuan3D-2')
ap.add_argument('--steps', type=int, default=30); ap.add_argument('--octree', type=int, default=256); ap.add_argument('--seed', type=int, default=1234)
a = ap.parse_args()
t0 = time.time()
c = Client(a.space, token=os.environ.get('HF_ALL') or os.environ.get('HF_TOKEN'), verbose=False)
res = c.predict(caption=None, image=handle_file(a.image), mv_image_front=None, mv_image_back=None, mv_image_left=None, mv_image_right=None,
                steps=a.steps, guidance_scale=5.0, seed=a.seed, octree_resolution=a.octree, check_box_rembg=True, num_chunks=8000,
                randomize_seed=False, api_name='/shape_generation')
print('result:', [type(r).__name__ for r in res], f'{time.time()-t0:.0f}s')
for r in res:
    path = r.get('value') if isinstance(r, dict) else r
    if isinstance(path, str) and os.path.exists(path) and path.lower().endswith(('.glb', '.obj', '.ply', '.stl')):
        shutil.copy(path, a.out); print('saved', a.out, os.path.getsize(a.out)); break
else:
    print('no mesh file in result:', res)
