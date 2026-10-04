# BiliBili 字幕下载工具 (bilibili-decoder)

本地批量下载 B 站字幕：**优先下载服务器端现成字幕（AI 字幕 / UP 主上传）**，无字幕时自动回退到**本地语音转写（FunASR Paraformer）**。输出带时间轴的 `.srt` 和 `.md` 文件，按 UP 主分文件夹存放。

## 功能

- **现成字幕下载**：登录后通过 B 站官方 API（WBI 签名）获取 AI 字幕 / UP 主上传字幕，批量、快速（9 个视频约 3 秒）
- **本地转写回退**：早期无字幕视频自动下载音频，用 FunASR（中文优化）本地转写，CPU 上约 12 倍速，免费无限量
- **多种批量入口**：单视频、URL 列表文件、**按 UP 主爬取（全部 / 最近 N 条 / 标题关键词筛选）**、关键词搜索
- **多 P 视频**：默认下载**全部分 P**，文件名带 `P2-副标题` 标识，互不覆盖
- **简介下载**：`.md` 文件同时包含视频**简介**（`## 简介` 章节，来自 B 站，随字幕一并保存）
- **关键词分组下载**：搜索结果可统一收进 `输出目录/group_<关键词>/`（不按 UP 主打散，见 `search_group.bat`）
- **输出格式**：`.srt`（毫秒级时间轴）+ `.md`（`MM:SS 文本` 时间轴，类似 vCaptions 文档格式）
- **目录结构**：`输出目录/UP主名/视频标题 [BVID].srt|.md`

## 环境要求

- Windows / macOS / Linux，Python 3.10+
- 磁盘：虚拟环境约 1.4 GB（torch 为主）+ 模型缓存约 2 GB（首次转写时下载到项目内 `models_cache`，均在项目所在盘）
- 网络：首次使用需下载模型（约 2 GB）；之后离线可用

## 安装

```bat
cd e:\BiliBiliDecoder
python -m venv .venv
.venv\Scripts\activate            :: Windows
:: source .venv/bin/activate     :: macOS / Linux
pip install -r requirements.txt
```

> ffmpeg 可选：系统装了更好；未安装时工具会自动使用 `imageio-ffmpeg` 内置的 ffmpeg 二进制。

## 配置登录 Cookie（推荐，可获取现成字幕）

B 站字幕接口**必须登录**才能访问。把 Cookie 保存到项目根目录 `cookie.txt`（以 `#` 开头的行会被忽略）：

1. 打开已登录的 `bilibili.com`，按 `F12` → **Application(应用)** → **Cookies** → `https://www.bilibili.com`
2. 复制 `SESSDATA` 的 Value，写入 `cookie.txt`：

```
SESSDATA=你的值
```

（也可在 Network 里复制播放器请求的完整 Cookie 头，多行每行一个 `key=value`。）

`cookie.txt` 已在 `.gitignore` 中，不会被提交。

## 双击运行（最快上手）

无需敲命令，直接用列表文件 + 批处理：

1. 编辑 **`list.txt`**，每行一个条目，支持多种格式（`#` 开头为注释）：

   ```
   https://www.bilibili.com/video/BV1AiuJ6QE9q/   # 视频链接
   BV1s2421Z7qJ                                   # BVID
   https://space.bilibili.com/87330354            # UP 主空间链接
   up:87330354                                    # 指定 UP 主
   search:关节电机                                 # 关键词搜索
   D:\videos\我的视频.mp4                          # 本地视频/音频（直接本地转写）
   ```

2. 双击 **`run.bat`** 即可，字幕输出到 `subtitles\UP主名\`；本地文件的字幕输出到**视频同目录**。

`run.bat` 顶部可配置：`LIST`（列表文件）、`OUT`（输出目录）、`RECENT`（列表中的 UP 主抓取数量：`ALL`=全部 / 数字=最近 N 个）、`TAG`（标题关键词筛选）、`MAX`（搜索条目的结果数）、`SKIP`（已下载跳过，默认 1）、`LOUDNORM`（列表本地文件响度放大，默认 0）、`SAVE_VIDEO`（列表本地文件同时导出放大视频，默认 0）。

## 使用

所有命令加 `--cookie-file cookie.txt` 即可读取登录态。

### 1. 下载单个视频

```bat
.venv\Scripts\python.exe -m bilibili_decoder video "https://www.bilibili.com/video/BV1AiuJ6QE9q/" --cookie-file cookie.txt
:: 支持多个：video URL1 URL2 ...
```

### 2. 批量（列表文件，支持多格式混合）

`list.txt` 每行一个条目（`#` 开头为注释），支持**本地文件 / 视频链接 / BVID / UP 主 / 搜索**混排（格式见"双击运行"一节）：

```bat
.venv\Scripts\python.exe -m bilibili_decoder batch -f list.txt --cookie-file cookie.txt
```

`batch` 也支持 UP 主/搜索的控制参数：`--all`（UP主全部）、`--recent N`（UP主最近N个）、`--tag 关键词`（UP主标题筛选）、`--max N`（搜索结果数）；列表中的本地文件条目支持 `--loudnorm` / `--volume` / `--save-video`（见第 7 节）。

### 3. 按 UP 主爬取

```bat
:: 最近 30 个（默认）
.venv\Scripts\python.exe -m bilibili_decoder up 87330354 --cookie-file cookie.txt

:: 最近 10 个
.venv\Scripts\python.exe -m bilibili_decoder up 87330354 --recent 10 --cookie-file cookie.txt

:: 全部视频
.venv\Scripts\python.exe -m bilibili_decoder up 87330354 --all --cookie-file cookie.txt

:: 只处理标题含"关节电机"的
.venv\Scripts\python.exe -m bilibili_decoder up 87330354 --all --tag 关节电机 --cookie-file cookie.txt
```

UP 主 mid 可从其空间页链接获得（`https://space.bilibili.com/87330354`）。

### 4. 关键词搜索

```bat
.venv\Scripts\python.exe -m bilibili_decoder search 电机 --max 20 --cookie-file cookie.txt
```

### 5. 强制本地转写 / 跳过转写

```bat
:: 不用现成字幕，强制 FunASR 转写（用于对比效果）
.venv\Scripts\python.exe -m bilibili_decoder video BV1AiuJ6QE9q --force-stt --cookie-file cookie.txt

:: 只下载现成字幕，无字幕就跳过（不做转写）
.venv\Scripts\python.exe -m bilibili_decoder up 87330354 --all --no-stt --cookie-file cookie.txt
```

### 6. 一键清理缓存

```bat
:: 清理 __pycache__、下载残留(.part)、转写临时文件
.venv\Scripts\python.exe -m bilibili_decoder clean

:: 同时删除 STT 模型缓存 models_cache（约 2GB，下次转写需重新下载）
.venv\Scripts\python.exe -m bilibili_decoder clean --models
```

> 转写过程产生的音频、16k wav 中间文件放在系统临时目录，**用后自动清理**；
> 只有加 `--keep-audio` 时才会把原始 `.m4a` 保留到 UP 主目录。

### 7. 转写本地视频 / 音频文件

```bat
:: 提取音频 + FunASR 转写，在视频同目录生成同名 .srt/.md
.venv\Scripts\python.exe -m bilibili_decoder local "D:\视频\我的视频.mp4"
:: 支持多个文件（mp4/mkv/flv/mp3/wav...）
.venv\Scripts\python.exe -m bilibili_decoder local a.mp4 b.wav

:: 音频很轻时：响度归一化自动放大（推荐）+ 同时导出放大版视频
.venv\Scripts\python.exe -m bilibili_decoder local "D:\视频\很轻.mp4" --loudnorm --save-video

:: 或手动指定放大倍数
.venv\Scripts\python.exe -m bilibili_decoder local a.mp4 --volume 5
```

> 本地文件也可以直接写进 `list.txt`，用 `batch` 一起批量处理（同样支持 `--loudnorm` 等参数）。
### 8. 关键词分组下载（`search_group.bat`）

双击 **`search_group.bat`**，按提示输入**关键词**和**条数**，搜索结果会统一放进一个文件夹：

```
subtitles\group_<你输入的关键词>\
├── 视频A [BV1xxx].srt / .md
├── 视频B [BV1yyy].srt / .md
└── ...（不按 UP 主打散，便于检索）
```

等价的命令行写法：

```bat
.venv\Scripts\python.exe -m bilibili_decoder search 强化学习 --max 20 --group --cookie-file cookie.txt
:: --group 不加值 → 自动用关键词作文件夹名（group_强化学习）
:: --group 我的专题 → 自定义名称（group_我的专题）
```
### 常用参数

| 参数 | 说明 |
|---|---|
| `--out DIR` | 输出目录（默认 `subtitles`） |
| `--formats srt,md` | 输出格式（默认 `srt,md`） |
| `--lang zh` | 优先字幕语言（默认 zh） |
| `--no-stt` | 仅下载现成字幕，跳过转写 |
| `--force-stt` | 忽略现成字幕，强制本地转写 |
| `--skip-existing` | 目标文件已存在则跳过（避免重复转写/下载，`run.bat` 默认开启） |
| `--group [名称]` | 本次全部文件统一放入 `<输出目录>/group_<名称>/`（不加值则自动用关键词/UP主 mid） |
| `--hotword 电机,机器人` | 转写热词（可提升特定词汇准确率） |
| `--keep-audio` | 保留下载的音频（.m4a） |
| `--volume 5` | 本地转写音频放大倍数（默认 1.0） |
| `--loudnorm` | 本地转写响度归一化自动放大（音频很轻时推荐） |
| `--save-video` | 本地转写同时导出放大版视频（原名_放大.mp4） |
| `--cookie-file cookie.txt` | 从文件读取登录 Cookie |
| `-v` | 输出调试日志 |

## 输出示例

```
subtitles/
└── 电机机器人与哲学DAMOTO/
    ├── 一个讲电机电控和机器人的频道为什么能未来十年不断更？ [BV1AiuJ6QE9q].srt
    └── 一个讲电机电控和机器人的频道为什么能未来十年不断更？ [BV1AiuJ6QE9q].md
```

`.md` 内容（带时间轴，便于阅读/喂给 LLM）：

```
# 一个讲电机电控和机器人的频道为什么能未来十年不断更？

> https://www.bilibili.com/video/BV1AiuJ6QE9q

> 字幕来源：AI字幕（zh）

## 简介

（视频简介文字，来自 B 站，随字幕一并下载）

## 完整口播

00:00 很多在校的或者刚毕业的这个年轻人呢
00:03 想转这个电机和运动控制这个方向的呃
00:07 自己在默默的这个学习和探索
...
```

## 注意事项

- **字幕接口需登录**：未登录时大部分视频拿不到现成字幕（会走本地转写）；登录后绝大多数近期视频可直接下载
- 登录后才可见的视频（会员/充电等）需要对应权限的 Cookie
- 首次使用 STT 会下载约 2 GB 模型到 `models_cache`（在项目所在盘），之后离线可用；删除该目录可释放空间
- 转写输出无标点（FunASR 标点模型句对齐失败的已知现象），但时间戳完整
- **转写速度（batch_size_s）**：`stt/engine.py` 里 `batch_size_s=300`（默认每批处理 300 秒音频）。把它调大（如 600）可让多核 CPU 更快、内存占用略增，**识别结果完全一致**（批大小只影响并行计算，不影响准确率）；调小则更慢但更省内存。这是纯并行优化，改不改都不影响识别内容。
- **B 站风控（HTTP 412）**：UP 主/搜索等接口会被 B 站随机拦截（返回 412 拦截页）。工具已内置三层防护：①每次重试**重新生成签名**（默认 8 次、递增退避）；②UP 主爬取失败时**自动切换手机端接口**（appkey 签名，风控较弱）重新爬取；③翻页间隔 1 秒降低触发概率。若某次仍失败，重新运行即可。
- **失败阈值保护**：单次运行失败超过 **10 项**时，会告警提示 Cookie/令牌可能已过期，并中断剩余任务；更新 `cookie.txt` 后重跑即可（已下载的会自动跳过）。
- **查询失败 ≠ 无字幕**：若字幕接口查询失败（风控/网络），工具会**跳过该视频并告警**，而不会误当成"无字幕"去跑耗时的本地转写；稍后重跑即可补上。
- **搜索翻页**：B 站搜索每页混有"课堂/直播"等非视频条目，工具按接口返回的**总页数**翻页（最多 50 页 ≈ 1000 条），`--max N` 能真正取到 N 条；翻页间隔 0.5 秒降低风控。
- **窗口点击导致"暂停"**：传统 conhost 窗口开着「快速编辑模式」时，运行中点击/拖选窗口文字会让程序暂停（需按 Enter 恢复）。`run.bat` / `search_group.bat` 启动时会自动调用 `disable_quickedit.ps1` 关闭**本窗口**的该模式（会打印 `[QuickEdit] ...` 提示），其他终端不受影响。若提示不支持，可在窗口标题栏右键 → 属性 → 选项 中手动取消勾选「快速编辑模式」。

## 目录结构

```
bilibili_decoder/
├── api/        B 站 API 客户端（WBI 签名、视频/字幕/音频/搜索）
├── fetch/      字幕抓取、音频下载与 ffmpeg 转换
├── stt/        FunASR 本地转写
├── output/     .srt / .md 写出
└── cli.py      命令行入口
scripts/        开发辅助脚本（字幕可用性扫描、UP主检查等）
```
