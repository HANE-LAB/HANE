# 部署与恢复

[文档目录](README.md) · [安装与更新](GETTING_STARTED.md)

网站：[HANE](https://hane-lab.github.io/HANE/) · 源码：[HANE-LAB/HANE](https://github.com/HANE-LAB/HANE) · 离线版：[HANE-offline.zip](https://github.com/HANE-LAB/HANE/releases/download/offline/HANE-offline.zip)

## 发布方式

每日采集在受控本机使用登录态更新动态、直播和图片，用 Hy-MT 补译新增或变更内容；HANE-LAB 收到归档更新后自动构建网站与离线包。
计划时间为 **日本时间 09:23 / 中国时间 08:23**，实际更新依赖本机在线和登录态有效。
云端不保存 B 站 Cookie 或翻译 API key；本机任务未执行或采集失败时，网站继续保留已有归档。

准备环境、更新命令、正式版与开发版的区别见[安装与更新](GETTING_STARTED.md)，登录态与数据保存位置见[采集与归档](ARCHIVE.md)。

在自己的仓库执行 `lab.py publish` 会先同步远端，再更新并提交 `data/`。
失败或部分完成时，已取得的内容仍会保留并尝试上传，最终返回非零退出码；请检查终端或开发版。

## 启用 GitHub Pages

1. 将代码与完整归档数据提交到自己的 GitHub 仓库。
2. 在 Settings → Pages → Source 选择 **GitHub Actions**。
3. 在 Actions → **发布 HANE** 中点击 **Run workflow**。

更换电脑或迁移仓库时重新准备环境；不要上传本机配置、虚拟环境、模型、沙盒或备份。

## 工作流与触发条件

构建工作流定义在 [update-and-deploy.yml](../.github/workflows/update-and-deploy.yml)。
推送 `main` 且涉及 `data/`、`hinome/`、回归测试、配置、依赖或工作流时触发发布；也可手动运行。
纯 README 或 `docs/` 修改不会自动重建网站。仅改页面代码无需重新采集数据。

| Job | 内容 |
|---|---|
| `build` | 安装依赖、运行六组回归、使用归档构建正式版、检查体积，准备网站 artifact 与离线 ZIP |
| `deploy` | 在构建成功后发布 Pages artifact |
| `offline` | 在构建成功后更新 Release「offline」的 ZIP；下载地址固定，旧文件被替换 |

PR 运行同一工作流的回归与构建，跳过 Pages 配置、artifact 上传、离线打包和发布，不更新线上网站。
`deploy` 与 `offline` 都依赖 `build`，两项发布结果需分别查看。

工作流默认权限是 `contents: read`、`pages: write`、`id-token: write`；只有 `offline` job 使用 `contents: write` 更新 Release。
无需配置采集或翻译 Secrets。

## 每日自动采集

本机定时采集先合并远端归档，再登录更新和补译；保留原档、历史、缓存与校订。常规数据推送会触发 **发布 HANE**。
日常增量与定期历史复核使用[采集与归档](ARCHIVE.md)中的同一规则，登录态过期或遭遇风控会明确失败，不降级冒充完整更新。

GitHub Actions 只负责回归、网站与离线包构建发布，不提供云端采集任务。
Hy-MT 的模型与运行包留在本机，译文缓存和校订随 `data/` 提交；补译与缓存规则见[翻译](TRANSLATION.md)。
本机采集结果与云端构建结果应分别检查；采集或推送失败时保留本地归档与提交，恢复方式见下文。

### HTTP 412 与游客可见性

GitHub 云端能运行任务，不代表 B 站允许其游客请求。HTTP 412 可能涉及出口网络、身份或请求频率，
不能仅凭状态码认定是抓取太快，也不能保证加大间隔就会恢复。`-352` 风控校验失败同样停止本次采集。
初始化或翻页遇到风控、限流时都会停止，不切换请求器、不继续查询粉丝数；已有归档和断点保留。

2026-10-19 使用同版本请求库做单页对照，初始化接口均正常，动态列表接口的结果如下：

| 环境与身份 | 动态列表结果 |
|---|---|
| GitHub 托管 Ubuntu runner，游客 | HTTP 412 |
| 本机，游客 | HTTP 200 / code 0，但列表为空 |
| 同一本机，已有有效登录态 | HTTP 200 / code 0，返回 12 条且还有下一页 |

这说明当次游客采集不可用，不能把空列表当作没有新动态或历史结束；也不能由本机结果推断云端登录一定可用。
持续受限时需在可正常访问来源的受控环境中登录采集，云端继续使用已保存归档构建；仅改变定时器不能解决来源访问限制。
不要把失败任务标成成功，不要将个人 Cookie 写入公开仓库、日志或构建 artifact。

## 发布内容

- 构建命令固定为 `python lab.py process --no-open --backend none --edition release`，仅读取已有且匹配原文的译文缓存。
- 仅 `site/` 进入网站与离线包；`site-dev/` 和本机诊断日志不发布。
- 页面内嵌压缩编码的数据，工作流会移除仅供本机测试的 `site/data.json`。压缩不是加密，仓库中的 `data/` 仍公开。
- 构建退出码 `2` 表示部分完成或警告，页面已生成时允许继续发布；退出码 `1` 或测试失败会阻止发布。
- `site/` 达到 1,000,000,000 字节时工作流停止发布，不会自动删除图片或历史。容量依据见 [GitHub Pages 官方限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)。

## 备份与失败恢复

独立备份整个 `data/`；备份范围见[文件与备份](ARCHIVE.md#文件与备份)。生成的网页不能替代原档。

`publish` 推送失败时，本地数据和提交仍保留。恢复网络或登录后检查 `git status`、`git log`，再重试 `git push`。
若远端有新提交，先保存两侧数据再合并；`publish` 会注册 `hinome.merge` 数据合并驱动。
不要用重置或删除历史目录来解决冲突。

如果 `publish` 拉取到程序或依赖更新，它会在采集前停止，避免混用新旧模块。
按终端提示更新依赖后重新运行即可。网站更新问题先看 Actions 的具体失败 job，再检查对应构建或部署步骤。
