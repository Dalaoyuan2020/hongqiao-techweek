# cad/ · 科鲸壳与配件

> STL 成品**不进本仓库**（含原版奶龙外壳的接口几何，版权归原作者），只在群内流转。
> 本仓库只放生成脚本：有原版模型包的人跑一遍脚本，就能得到同样的 STL。

## 一键生成

```bash
python3 -m venv .venv && .venv/bin/pip install trimesh manifold3d numpy scipy scikit-image shapely lxml
# 先把奶龙模型包解压，01_奶蛙外壳.stl 复制为 models/01-shell.stl（底座/卡销同理：02-base / 03-pin-r / 04-pin-l）
.venv/bin/python cad/build_kejing.py --res 0.45 --out cad/kejing_shell_v1.stl   # 科鲸壳 + 14 项自动检查
.venv/bin/python cad/build_accessories.py                                        # 导游帽 / 小水柱 / 导游旗
```

产出：

| 文件 | 是什么 |
|---|---|
| `kejing_shell_v1.stl` | 科鲸壳，替换原版 `01_奶蛙外壳.stl`，其余 7 件原版不动 |
| `kejing_shell_v1_CHECKS.md` | 自动检查表（扣合、卡销、屏幕可视、重心、重量） |
| `kejing_shell_v1_paint.glb` | 上色示意（蓝身、白肚、黑眼、红嘴、深灰屏框） |
| `kejing_shell_v1_keep_zone.stl` / `_forbidden_zone.stl` | 给手工建模的同学：保留区（照抄原壳）/ 禁区（不许长东西） |
| `guide_hat.stl` / `water_spout.stl` / `guide_flag.stl` | 配件（全原创） |

## v2 流水线（当前用这个，AI 造型 + 原版接口）

```bash
.venv/bin/python cad/gen3d_hunyuan.py <效果图.png> cad/gen3d/<name>.glb            # 效果图 → 3D（混元 3D，HF 免费额度）
.venv/bin/python cad/build_kejing_v2.py --res 0.4 --ai cad/gen3d/B3d_1.glb \
    --landmarks cad/kejing_v2e_landmarks.json --out cad/kejing_shell_v2e.stl       # 拼接口 + 换尾巴 + 斜顶 + 20 项检查
.venv/bin/python cad/face_features.py cad/kejing_shell_v2e.stl                     # 从建模里量出眼睛/腮红/嘴的真实轮廓（必须在上色前跑）
.venv/bin/python cad/paint_v2.py cad/kejing_shell_v2e.stl                          # 上色示意 GLB
.venv/bin/python cad/color_split_v2.py cad/kejing_shell_v2e.stl                    # 4 色打印件 + 手绘描边版
```
本机看模型：`open "http://127.0.0.1:8765/cad/tools/viewer.html?shell=/cad/kejing_shell_v2e_paint.glb"`（先在仓库根目录 `python3 -m http.server 8765`）。

## 做法（为什么接口不会错）

结果 = （科鲸造型 − 禁区）∪ 保留区。保留区是原壳在底座四周 3 mm、顶板和两个卡销凸台的部分，**逐个三角面照抄原壳**；禁区是底座、卡销通道、卡销帽外侧和 Z<0。
造型部分用 SDF（距离场）雕：身体椭球 + 圆角裙边 + 鱼鳍 + 尾巴 + 眼睛 + 笑嘴 + 屏框，参数都在 `build_kejing.py` 顶部，改造型只动那一段。

## 打印与装配

- 按毫米原尺寸打印，**不要缩放**。PLA，0.2 mm 层高，填充 15%。
- 壳：底面朝下摆放。腔体顶板和尾巴需要支撑；卡销通道（8.4 mm 方孔）和腔体内壁的支撑要清干净。
- 帽子、水柱：底面挖了贴合头顶的弧面，需要少量支撑。旗：平躺打印，旗面和旗杆都贴床。
- 磁铁：Ø10×2 mm 钕磁铁 3 颗（壳顶 1、帽子 1、水柱 1），502 胶粘进 Ø10.4×2.4 槽。**先试好极性再粘**，帽子和水柱要被壳顶吸住。
- 旗杆 Ø3.0，插机器人右手（左边那只鳍）的 Ø3.3 斜孔，深 12 mm，向前倾 32°（避开头部）。孔打小了用 3 mm 钻头通一下。
- 上色：身体 Datawhale 蓝，肚皮（抬高 1.2 mm 的区域）白，眼睛黑（可贴眼睛贴纸），嘴红，屏框深灰。

## 实测接口（与 docs/interface_spec.md 不同的地方）

见 `docs/shell_interface_measured.md`。要点：屏幕是装在**底座正面**的 1.54 寸**方屏**（窗口 28×29.5 mm），外壳只要在前面让开；3MF 是打印摆盘，不是装配关系。
