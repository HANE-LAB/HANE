# HANE

火羽ひのめ的非官方动态与直播档案。保存 B 站 UID `2094031249` 的动态、图片、译文和历史快照，生成可在线或离线浏览的静态网站。

[在线浏览](https://hane-lab.github.io/HANE/) · [公开源码](https://github.com/HANE-LAB/HANE) · [离线版下载](https://github.com/HANE-LAB/HANE/releases/download/offline/HANE-offline.zip)

## 使用方式

- **直接浏览**：打开在线网站，查看动态环、直播、统计和全文归档。
- **离线浏览**：下载 `HANE-offline.zip`，解压后双击 `index.html`；字体与未归档图片可能需要联网。
- **本地维护**：按[安装与更新](docs/GETTING_STARTED.md)准备环境。Windows 可运行 `run_windows.bat`，macOS / Linux 可运行 `bash run_mac.command`；默认会联网采集和更新数据。

项目采用本地手动采集、GitHub Actions 构建发布，无数据库和常驻后端。Actions 只使用已提交的数据，不抓取、不使用登录凭证。

## 文档导航

| 想做什么 | 文档 |
|---|---|
| 安装、更新数据、查看本地页面 | [安装与更新](docs/GETTING_STARTED.md) |
| 理解鸟居、光束、御守、直播与小猪交互 | [浏览与读图](docs/USAGE.md) |
| 录制动态环视频、控制镜头 | [录制模式](docs/RECORDING.md) |
| 配置采集、了解数据来源、备份与缺失口径 | [采集与归档](docs/ARCHIVE.md) |
| 准备离线翻译、使用缓存和校订 | [翻译](docs/TRANSLATION.md) |
| 修改代码、查找模块、运行测试 | [开发指南](docs/DEVELOPMENT.md) |
| 部署 GitHub Pages、下载离线包、恢复推送 | [部署与恢复](docs/DEPLOY.md) |

完整目录及文档维护分工见 [docs/README.md](docs/README.md)。

## 数据说明

归档不包含评论正文、逐条弹幕、视频或直播原文件；缺失记录不能推断为没有活动。机器翻译可能误解省略主语和梗，原文始终保留。请独立备份整个 `data/`，生成的 `site/` 不能代替原档。
