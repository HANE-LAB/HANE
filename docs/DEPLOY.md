# 部署与恢复

[文档目录](README.md) · [安装与更新](GETTING_STARTED.md)

网站：[HANE](https://hane-lab.github.io/HANE/) · 源码：[HANE-LAB/HANE](https://github.com/HANE-LAB/HANE) · 离线版：[HANE-offline.zip](https://github.com/HANE-LAB/HANE/releases/download/offline/HANE-offline.zip)

## 发布方式

HANE-LAB 每天自动以游客身份采集动态、同步直播和补图，保存归档后构建网站与离线包。
默认时间为 **UTC 00:23 / 日本时间 09:23 / 中国时间 08:23**；Actions 排队时可能延迟。
本机维护时使用登录态补全可访问内容、翻译和校订。云端不使用 B 站 Cookie，也不下载翻译模型。

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

HANE-LAB 中的 `.github/workflows/daily-update.yml` 每天运行，也可在 Actions → **每日更新归档** 中手动启动。
该任务仅在 `HANE-LAB/HANE` 的 `main` 上采集；普通克隆或开发环境不会自行联网运行。

1. 检出最新 `main`，执行 `lab.py publish --guest --no-open --backend none --edition release`。
2. 同步并保存两侧归档，仅提交 `data/`；游客模式不会使用环境或本机配置中的登录态。
3. 显式触发 **发布 HANE**，运行回归并更新网站和离线包。

必须显式触发构建，因为 [GitHub 的 `GITHUB_TOKEN` 推送不会再次触发 push 工作流](https://docs.github.com/en/actions/concepts/security/github_token)。
每日任务使用 `contents: write` 保存数据、`actions: write` 触发构建，不需要额外访问令牌。

新动态会先显示原文，已有匹配的译文缓存继续使用；新译文由后续本地维护补充。
游客没返回的动态不会被标记不可见；游客响应也不会覆盖登录采集的正文，只刷新其互动数。
因此，登录取得的正文若后来编辑，需下一次本地登录采集才能确认。完整性规则见[采集与归档](ARCHIVE.md)。

采集失败时保留旧数据，不把失败当作完整更新。任务失败会保留 `archive-recovery-运行编号` artifact 30 天，
其中包含本次工作目录的归档，尤其用于恢复推送冲突时尚未上传的数据。失败后的恢复应合并数据，禁止强推覆盖远端。
退出码 `2` 的部分完成允许保存和构建，但需要查看日志；退出码 `1` 不触发新的构建。
每日采集与网站构建是两条独立的 Actions 记录，需要分别检查运行结果。

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
