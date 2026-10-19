# HANE 的发布与本地更新

网站：https://hane-lab.github.io/HANE/

仓库：https://github.com/HANE-LAB/HANE

离线版：https://github.com/HANE-LAB/HANE/releases/download/offline/HANE-offline.zip

当前采用本地手动采集、GitHub Actions 构建发布。Actions 不抓取动态或直播，不使用 Cookie、不下载翻译模型；两类数据都在本机更新。

## 日常更新

在项目目录打开 PowerShell，执行：

```powershell
# 抓取动态、同步直播、补图、翻译，再上传归档并触发线上发布
.\.venv\Scripts\python.exe lab.py publish

# 只更新本地，暂时不上传
.\.venv\Scripts\python.exe lab.py update

# 查看正式版，不联网
.\.venv\Scripts\python.exe lab.py open
```

`publish` 会先同步远端，再更新并提交 `data/`。失败或部分完成会保留已取得的内容，并尝试上传，最终仍返回非零退出码；请检查终端输出或开发版，不要只凭网站能打开判断采集成功。Cookie 只放在本机 `config.local.toml`；获取方法见 README。没有配置系统计划任务，需要更新时手动执行。

仅改页面代码时，提交并推送代码即可，无需重新抓取。改动 `hinome/`、`data/`、配置、依赖、回归测试或工作流会触发发布。仅修改 README 不触发部署；也可在 Actions → **发布 HANE** → **Run workflow** 手动重建。

## 两个版本

```powershell
# 用缓存生成正式版
.\.venv\Scripts\python.exe lab.py process --backend none --edition release --no-open

# 生成并打开开发版
.\.venv\Scripts\python.exe lab.py process --backend none --edition dev --no-open
.\.venv\Scripts\python.exe lab.py open --edition dev
```

- `site/`：正式版，保留内容与可视化，隐藏采集进度、失败日志、PIPELINE、归档调试和图片制作来源。
- `site-dev/`：开发版，保留完整诊断入口；已加入 `.gitignore`。
- `logs/`：本机运行诊断，供开发版读取，不提交到 GitHub。
- `data/`：两版共同使用的历史原档，不因切换版本删除。公开仓库中的数据仍是公开的，开发版不是访问权限隔离。

线上工作流固定 `--backend none --edition release`，只使用已有且匹配原文的译文缓存，不下载模型。新增翻译在本机完成；校订稿仍优先保留。直播缺年、场次不完整、金额口径等内容解释在正式版保留。

## GitHub 设置与发布流程

在自己的 GitHub 仓库启用网站：

1. 提交代码和归档数据。
2. 在 Settings → Pages → Source 选择 **GitHub Actions**。
3. 在 Actions → **发布 HANE** 点 **Run workflow**。

换电脑或迁移到新仓库时，上传代码和完整 `data/`，按上面的步骤设置 Pages。不要上传本机配置、虚拟环境、模型、沙盒或备份。

工作流有三个 job：

1. `build`：安装依赖，运行离线回归，用已提交归档生成正式版，删掉 `site/data.json`（页面已内嵌压缩编码的数据），检查体积，上传 Pages artifact，并把 `site/` 打包成 `HANE-offline.zip`。
2. `deploy`：发布该 artifact。构建或测试失败时不发布新的站点。
3. `offline`：把 `HANE-offline.zip` 上传到 Release「offline」，替换旧文件。第一次运行时自动建立这个 Release，下载地址固定不变。

拉取请求（PR）也会触发同一工作流，但只运行 `build` 里的回归和构建，跳过 Pages 配置、上传、打包、`deploy` 和 `offline`，不会改动线上网站。

工作流的权限为 `contents: read`、`pages: write`、`id-token: write`；只有 `offline` 用 `contents: write` 更新 Release。不需要 `BILI_SESSDATA`、`BILI_BUVID3` 或翻译 Secrets。`site-dev/` 不进入 Pages artifact。

## 备份与恢复

- 定期独立备份**整个 `data/`**，包括动态原始响应、图片、互动快照、译文及直播版本。网页生成物不能替代原档。
- `publish` 推送失败时，本地归档和提交仍保留。恢复网络或登录后检查 `git status` / `git log`，再重试 `git push`。若远端有新提交，先保存两侧数据再合并；`publish` 会注册 `hinome.merge` 数据合并驱动。不要用重置或删除历史目录来解决冲突。
- 工作流在 `site/` 达到 1,000,000,000 字节时停止发布，不会自动删图或删历史。接近容量阈值时先备份，再规划托管方式。[GitHub Pages 官方限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
