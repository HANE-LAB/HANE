# 开发指南

[文档目录](README.md)

## 环境与代码结构

先按[安装与更新](GETTING_STARTED.md)准备 Python 环境；JavaScript 测试需要 Node.js。
代码按采集、归档、规整、翻译、分析、构建分层，无数据库和常驻后端。

| 位置 | 职责 |
|---|---|
| `lab.py`、`hinome/cli.py` | 命令入口与流程编排 |
| `hinome/util.py` | 路径、配置、日志、JSON 读写、数据锁 |
| `hinome/fetch.py` | B 站动态采集、WBI 签名、断点与增量核对 |
| `hinome/archive.py` | 图片归档、动态版本与互动快照 |
| `hinome/live.py` | Danmakus 直播原档、修订、同步状态与页面数据 |
| `hinome/normalize.py` | 将不同动态类型规整为统一结构 |
| `hinome/translate.py`、`hinome/local_mt.py` | 翻译后端、缓存、校订、离线模型 |
| `hinome/analyze.py` | 标签、关键词、互动分和译文自检 |
| `hinome/build.py` | 页面数据、图片与资源打包，正式版／开发版输出 |
| `hinome/template.html` | 单文件前端：HTML、CSS、JavaScript 与 Canvas/WebGL 渲染 |
| `hinome/merge.py` | 多端归档合并，保留历史与登录正文、合并最新互动数据 |
| `hinome/assets/` | 人物、小猪和图标资源；来源见 [PROVENANCE.txt](../hinome/assets/PROVENANCE.txt) |
| `dev/` | 虚构数据、回归测试、预览和截图工具 |
| `.github/workflows/update-and-deploy.yml` | 回归、正式版构建、Pages 与离线包发布 |

归档文件与生成物的区别见[采集与归档](ARCHIVE.md#文件与备份)。

## 配置与数据边界

- 默认值定义在 `hinome/util.py`，由 `config.toml` 覆盖，再由本机 `config.local.toml` 覆盖；环境变量仅补充尚未填写的凭据。
- Cookie、API key 只放本机配置或环境变量，不能写入公共配置、日志、截图或提交。
- `update`、`process`、`publish` 会写真实 `data/`；开发验证使用沙盒，不用真实归档做实验。
- 不通过降低请求间隔增加采集频率。原档和历史版本不得为测试方便删除。
- 游客结果不能用于判断动态消失或覆盖登录正文；登录态有效性、身份切换、历史合并和并发推送都须用离线夹具验证。
- 翻译默认免费；原文保留，校订与缓存按原文匹配。具体规则见[翻译](TRANSLATION.md)。

## 沙盒预览

```powershell
.\.venv\Scripts\python.exe -X utf8 dev/demo.py
```

用虚构的「示例主播 Demo」生成 `dev/.sandbox/demo/site/` 和 `site-dev/`，不修改正式归档与页面。
`dev/fixture.py` 提供虚构数据，`dev/shots.py` 用于桌面、手机和不同数据量的视觉检查。

截图工具需要额外安装 Playwright 及 Chromium：

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -X utf8 dev/shots.py
```

## 回归检查

在项目根目录运行；以下六组与发布工作流保持一致：

```powershell
.\.venv\Scripts\python.exe -X utf8 dev/test_units.py
.\.venv\Scripts\python.exe -X utf8 dev/test_archive.py
.\.venv\Scripts\python.exe -X utf8 dev/test_translation.py
.\.venv\Scripts\python.exe -X utf8 dev/test_live.py
node dev/test_render.cjs
node dev/test_live.cjs
```

| 改动 | 检查范围 |
|---|---|
| `hinome/*.py` | 单元测试、受影响的归档／翻译／直播回归，以及 `dev/demo.py` |
| `hinome/template.html` | 渲染与直播回归，桌面和手机视觉检查；覆盖正式／开发版、空／少／多数据、默认播放与暂停拨动 |
| 纯文档 | 相对链接、命令与文件路径、目录分工；无需为文字移动重复运行功能测试 |
| 推送 `main` | 跑完上述六组回归；测试失败时工作流不会发布新站点 |

Windows 上使用 `-X utf8`，或先设置 `PYTHONUTF8=1`。`test_render.cjs` 会从模板抽取函数单独运行；新增函数依赖时要同步更新测试替身。

## 前端修改注意事项

- 主脚本是模块脚本，正式版使用顶层 `await` 解压嵌入数据；保持 `<script type="module">`，不要加入依赖全局函数的内联 `on*=` 事件。
- `hinome/template.html` 和 `run_windows.bat` 保持 CRLF 换行，避免修改少量代码却产生整文件差异。
- 动态与直播来源分开，缺失档案不能用动态里的预告或开播卡片补成实际场次。
- 改轮盘时检查[浏览行为](USAGE.md)和[录制接口](RECORDING.md)，保留键盘操作、手机布局、暂停／恢复与后台停绘逻辑。
- 功能改变后更新对应专题；首页只维护简介与导航。测试沙盒、截图、模型和备份不进入发行内容。
