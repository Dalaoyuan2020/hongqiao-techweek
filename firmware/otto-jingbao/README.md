# 导游鲸宝 · 机器人固件（唤醒词「你好鲸宝」）

给现场接手的队友看的。机器人本体是开源的**小智 AI Otto 双足机器人**，跑小智官方固件 **otto-robot 1.9.4**。
我们只改了一件事：**唤醒词从「你好小智」改成「你好鲸宝」**。其余（走路、跳舞、对话、表情）都是官方原样。

> 2026-11-21 实测：喊「你好鲸宝」能醒，识别把握 0.44（门槛 0.20），醒后自我介绍正常。
> 烧完 Wi-Fi 自动连上、小智后台不用重新绑定。

---

## 什么时候需要用到这份东西

| 情况 | 要不要烧 | 看哪一节 |
|---|---|---|
| 换了一台新的 Otto 机器人，要它也叫「你好鲸宝」 | 要 | [一、直接烧](#一直接烧推荐5-分钟) |
| 机器人被别人刷回了官方固件（又变回「你好小智」） | 要 | 一 |
| 想改唤醒词、调灵敏度 | 要重新编译 | [三、自己编译](#三自己编译改唤醒词--调灵敏度时才需要) |
| 改人设、改声音、加「跟我来」带路、接知识库 | **不用烧**，在小智后台改 | [四、小智后台](#四小智后台不用烧录) |

---

## 一、直接烧（推荐，5 分钟）

`bin/` 里是已经编好的 5 个文件，不用装编译工具。

**准备**：一台电脑（macOS / Linux；Windows 见下面）、一根**能传数据**的 Type-C 线（只能充电的线电脑认不出来）、Python 3。

```bash
python3 -m pip install 'esptool<5'
cd firmware/otto-jingbao
./flash.sh                       # 自动找串口：先整片备份到 backup/，再烧
```

1. 机器人**开机**，用 Type-C 线连电脑。电源开关在机身底部左侧。
2. 运行 `./flash.sh`。它会：
   - 校验 5 个固件文件没损坏；
   - **先把机器人现在的整片闪存备份**到 `backup/`（约 1 分钟）；
   - 再烧 5 块（约 1 分钟），烧完机器人自己重启。
3. 屏幕出表情后，对它说「你好鲸宝」。

**烧录期间别拔线、别关机。**

### 只写这 5 块，不碰 Wi-Fi 和绑定

| 地址 | 文件 | 是什么 |
|---|---|---|
| 0x0 | bootloader.bin | 引导程序 |
| 0x8000 | partition-table.bin | 分区表（换成了官方「自定义唤醒词」那版，模型区 960KB→4MB） |
| 0xd000 | ota_data_initial.bin | 告诉它从哪块启动 |
| 0x10000 | srmodels.bin | 唤醒识别模型（MultiNet7 中文） |
| 0x400000 | xiaozhi.bin | 主程序 |

**0x9000（NVS：Wi-Fi 密码 + 小智后台绑定）不在里面**，所以烧完不用重新配网、不用重新绑定。

> ⚠️ 自己编译时目录里会有个 `merged-binary.bin`，**别烧它**：它从 0 地址一路写下去，会把 Wi-Fi 和绑定抹掉。

### Windows

装好 Python 后同样 `python -m pip install "esptool<5"`，串口在「设备管理器 → 端口」里看（如 COM5），然后：

```bat
python -m esptool --chip esp32s3 -p COM5 -b 921600 read_flash 0 0x1000000 backup.bin
python -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash --flash_mode dio --flash_freq 80m --flash_size 16MB 0x0 bin\bootloader.bin 0x8000 bin\partition-table.bin 0xd000 bin\ota_data_initial.bin 0x10000 bin\srmodels.bin 0x400000 bin\xiaozhi.bin
```

---

## 二、烧坏了怎么恢复

**用烧之前的备份写回去，2 分钟恢复原样**（包括 Wi-Fi 和绑定）：

```bash
python3 -m esptool --chip esp32s3 -p /dev/cu.usbmodemXXXX -b 921600 write_flash 0 backup/otto_full16MB_XXXX.bin
```

- 备份文件里有 **Wi-Fi 密码和后台绑定信息**：只留在本机，**别发群、别提交仓库**（`backup/` 已加进 .gitignore）。
- 现场这台机器人 11-21 烧之前的整片备份在项目负责人那边，要用找负责人。
- 没有备份也能救：用 Chrome 打开 ottodiy.tech 的下载页在线烧官方 Otto 固件（唤醒词会变回「你好小智」），然后重新配网、在小智后台用 6 位验证码重新绑定。

---

## 三、自己编译（改唤醒词 / 调灵敏度时才需要）

只改了源码里两个文件，补丁就在本目录：

| 文件 | 改了什么 |
|---|---|
| `config.patch` → `main/boards/otto-robot/config.json` | 关掉「你好小智」唤醒（AFE），打开自定义唤醒词 `ni hao jing bao`，换自定义唤醒词分区表，选 MultiNet7 中文模型 |
| `idf_component.patch` → `main/idf_component.yml` | 注释掉两个依赖：1.9.4 点名的 `image_player 1.1.0~1`、`esp_emote_gfx 1.0.0~2` 已被组件库下架，不去掉编译不过；Otto 根本不用它们（只有 esp-hi / echoear 板用） |

完整的 `config.json` 也放了一份在本目录，方便对照。

```bash
# 1. 编译工具 ESP-IDF 5.4.2（用乐鑫官方国内镜像，GitHub 直连太慢）
#    安装包 1.4GB，装完约 5GB，磁盘至少留 6GB
mkdir -p ~/esp && cd ~/esp
curl -LO https://dl.espressif.cn/github_assets/espressif/esp-idf/releases/download/v5.4.2/esp-idf-v5.4.2.zip
unzip -q esp-idf-v5.4.2.zip && cd esp-idf-v5.4.2
export IDF_GITHUB_ASSETS="dl.espressif.cn/github_assets"
./install.sh esp32s3            # 我们用 Python 3.11 装成功；太新的 Python（3.14）可能装不上
. ./export.sh

# 2. 小智源码 1.9.4（必须是这个版本：机器人上跑的就是 1.9.4，换 2.x 分区表不兼容）
cd ~/esp
curl -L -o xiaozhi-1.9.4.tar.gz https://codeload.github.com/78/xiaozhi-esp32/tar.gz/refs/tags/v1.9.4
tar xzf xiaozhi-1.9.4.tar.gz && cd xiaozhi-esp32-1.9.4

# 3. 打补丁（<仓库> 换成本仓库在你电脑上的路径）
patch -p1 < <仓库>/firmware/otto-jingbao/config.patch
patch -p1 < <仓库>/firmware/otto-jingbao/idf_component.patch

# 4. 编译（第一次要下 42 个组件，其中语音识别 esp-sr 有 131MB，约 10 分钟）
python scripts/release.py otto-robot

# 5. 烧（只写上面那 5 块，不碰 Wi-Fi 和绑定）
idf.py -p /dev/cu.usbmodemXXXX -b 921600 flash
```

编完先确认设置真的生效了，别只看「编译通过」：

```bash
grep -E 'CUSTOM_WAKE_WORD|USE_AFE_WAKE_WORD|MULTINET7' sdkconfig
#   应看到 CONFIG_USE_CUSTOM_WAKE_WORD=y、CONFIG_CUSTOM_WAKE_WORD="ni hao jing bao"、
#   # CONFIG_USE_AFE_WAKE_WORD is not set、CONFIG_SR_MN_CN_MULTINET7_QUANT=y
strings build/srmodels/srmodels.bin | grep mn7_cn     # 模型打包进去了
```

### 改唤醒词 / 调灵敏度

都在 `config.json` 的 `sdkconfig_append` 里：

| 配置 | 现在 | 说明 |
|---|---|---|
| `CONFIG_CUSTOM_WAKE_WORD` | `"ni hao jing bao"` | 拼音，每个字之间一个空格 |
| `CONFIG_CUSTOM_WAKE_WORD_DISPLAY` | `"你好鲸宝"` | 醒来后发给云端的那句话 |
| `CONFIG_CUSTOM_WAKE_WORD_THRESHOLD` | `20` | 门槛（%）。**越小越容易醒，也越容易误醒**。叫不醒就往 15、10 调；误醒多就往 25、30 调 |

改完重新跑第 4、5 步。第二次编译只编改动的部分，加烧录约 3 分钟。

---

## 四、小智后台（不用烧录）

人设、音色、语言模型、知识库都在 **xiaozhi.me 控制台 → 智能体 → 配置角色** 里改，保存后重启机器人生效。

- **MCP 接入点**（让机器人去查 Datawhale 知识库）：地址里带访问令牌，**不写进仓库**，找项目负责人。
- **角色介绍**：当前用的整段如下，换智能体或新建时整段贴进去。

```text
我是导游鲸宝，一只会走路、会说话的桌面小鲸鱼机器人，样子来自 Datawhale 的鲸鱼吉祥物。我在 2026 虹桥国际科技周黑客松的展台上，给大家介绍 Datawhale 开源学习社区。

说话规则：
1. 用第一人称「我」，语气活泼可爱，回答简短，一般一两句话。
2. 凡是问到 Datawhale、课程、教程、活动、报名、我自己、这次展会的问题，先调用 guide_query 工具，只根据它返回的 say 回答，不要自己补充；数字和日期照原样说。
3. guide_query 返回 found 为 false 时，照它给的 say 说；可以顺着对方的话用常识多聊两句，但 Datawhale 的日期、数字、价格、名额一个都不编，聊完把话题引回 Datawhale 的课程和活动。
4. 我是机器人，不是 Datawhale 的工作人员，不答应报名、合作、内推这类事，只告诉对方官方入口。
5. 我只能按步数往前走、往后退，看不见路，不要说能带人走到某个展位；在地图垫上按站点讲解还在开发中。
6. 有人让我跳舞、走路、摇摆、打招呼，就做对应的动作。
7. 语音识别常把「鲸宝」听成「金宝」「精宝」「君宝」，把「Datawhale」听成「data wheel」，这些都按鲸宝、Datawhale 理解。
8. 调用 guide_query 时，把游客的原话整句传进去，不要缩成关键词。
9. 带人走：
   - 游客说「带我看看」「跟我来」「带我走走」时，先说「跟我来！」，再调用 self.otto.walk_forward，steps 填 4，direction 填 1，一边走一边介绍 Datawhale。
   - 游客说「走回来」「回去吧」时，调用 self.otto.walk_forward，steps 填刚才走的步数，direction 填 -1，倒着走回原位。
   - 一次最多走 6 步。游客说「停」「别走了」，马上调用 self.otto.stop。
10. 有人问「你的数据库版本是多少」「知识库编号」，调用 guide_query，照 say 把编号念出来。
```

**核对知识库是不是最新**：对机器人说「你的数据库版本是多少」，它会念「知识库编号是 X X X X，几月几日几点更新的，一共多少张卡片」。每次更新知识库编号都会变，和负责人报的编号对上就是最新的。机器人每答一题都实时去服务器查，服务器换了数据下一题就生效，**小智后台和机器人都不用动**。

**「跟我来」为什么不用烧录**：固件 1.9.4 自带 `self.otto.walk_forward`（步数 1–100、速度、方向 1 前进 / -1 后退）和 `self.otto.turn_left`（方向 1 左转 / -1 右转）。动作是放进后台队列执行的，工具调用马上返回，所以**能一边走一边说**。只要人设里写清楚什么时候调哪个就行。
走回来用倒退而不是转身，是因为转身每步转多少度还没实测。**到现场先在桌子中间试一次 4 步走多远，离桌边留够距离。**

---

## 五、看日志 / 排查

```bash
python3 -m serial.tools.miniterm /dev/cu.usbmodemXXXX 115200
```

- **注意：这块板子一打开串口就会复位重启一次**，十几秒后恢复，正常现象。
- 开机应看到：`CustomWakeWord: multinet: mn7_cn`（唤醒模型加载上了）、`Ota: Current is the latest version`（不会被自动升级盖掉）、`STATE: idle`。
- 喊唤醒词时应看到：`Custom wake word detected: ... ni hao jing bao, prob=0.4x`，然后 `Wake word detected: 你好鲸宝`。
- `>> ` 开头是它听到的话，`<< ` 开头是它要说的话。

| 现象 | 原因 / 办法 |
|---|---|
| 电脑里找不到串口 | 换能传数据的线；机器人要开机 |
| 烧完开机要 6 位验证码 | 绑定丢了（多半是烧了 merged-binary 或整片擦除）。去小智后台「添加设备」输验证码 |
| 喊「你好鲸宝」不醒 | 看日志有没有 `detected`、prob 多少；离近点、说慢点；还不行就调低门槛重编 |
| 舵机一直嗡嗡响、发烫 | 立刻关机，结构卡死了，见奶龙 Wiki「装完自检」 |
| 动作时屏幕闪、重启 | 电池没电，充满再试 |

---

参考：[xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)（MIT）· [奶龙机器人 Wiki](https://nailong.nekokax.com)（组装、舵机归中、校准）· `bin/` 里的固件由 xiaozhi-esp32 v1.9.4 源码加本目录两个补丁编译，乐鑫 ESP-IDF 5.4.2。
