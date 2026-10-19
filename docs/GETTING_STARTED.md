# 安装与更新

[文档目录](README.md)

## 准备环境

项目支持 Python 3.10 及以上，开发和 CI 推荐 Python 3.12。换电脑时重新创建虚拟环境，不要复制旧机器的 `.venv/`。

Windows 可双击 `run_windows.bat`，macOS / Linux 可运行 `bash run_mac.command`。脚本会准备虚拟环境和依赖，默认随后执行 `update`，会联网采集并写入归档。只想看已有页面时使用下方 `open` 命令。

手动安装（Windows PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

下文使用 Windows 命令；macOS / Linux 将 Python 路径替换为 `.venv/bin/python`。JavaScript 回归测试另需 Node.js，普通浏览无需安装。

## 日常命令

在项目目录打开 PowerShell：

```powershell
# 查看已有正式版，不联网
.\.venv\Scripts\python.exe lab.py open

# 更新本地：动态、直播、图片、翻译和页面
.\.venv\Scripts\python.exe lab.py update

# 更新后上传归档到当前仓库，触发 GitHub Pages 发布
.\.venv\Scripts\python.exe lab.py publish

# 只用已有数据和译文缓存重建，不抓取、不翻译
.\.venv\Scripts\python.exe lab.py process --backend none --no-open
```

第一次采集前可按[采集与归档](ARCHIVE.md)配置登录态，按[翻译](TRANSLATION.md)准备离线模型。
`publish` 会先同步当前仓库的远端，再更新、提交并推送数据；操作与失败恢复见[部署与恢复](DEPLOY.md)。

## 正式版与开发版

| 版本 | 生成位置 | 内容 |
|---|---|---|
| 正式版（默认） | `site/` | 动态环、直播、统计、全文与内容详情 |
| 开发版 | `site-dev/` | 正式版内容及抓取状态、数据链、版本记录、素材来源 |

生成并打开开发版：

```powershell
.\.venv\Scripts\python.exe lab.py process --backend none --edition dev
```

`open --edition dev` 可再次打开开发版。两版互不覆盖，GitHub 只发布 `site/`。

## 浏览器访问

离线版的使用方法见[浏览与读图](USAGE.md)。开发时若需要 HTTP 地址，在项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory site
```

打开 [本地页面](http://127.0.0.1:8765/)。按 `Ctrl+C` 停止服务；它仅监听本机。

## 其他常用操作

| 命令（接在 Python 路径后） | 作用 |
|---|---|
| `lab.py update --full` | 从头核对动态历史 |
| `lab.py update --guest --backend none --no-open` | 不使用登录态采集，以已有译文缓存生成页面 |
| `lab.py fetch --max-pages N` | 限制本次采集页数；不代表历史已抓完 |
| `lab.py live --no-open` | 单独同步直播档案并重建页面 |
| `lab.py media` | 补存归档图片 |
| `lab.py doctor` | 检查环境、网络和翻译后端；会联网 |
| `lab.py --help` | 查看当前版本的完整命令列表 |

## 完成状态

| 退出码 | 含义 |
|---|---|
| `0` | 完成 |
| `1` | 失败 |
| `2` | 部分完成或有警告 |
| `130` | 人工中断 |

页面生成成功不代表本次采集成功。出现警告时查看终端或开发版，保留已取得的数据后再处理。
