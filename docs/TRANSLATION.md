# 翻译

[文档目录](README.md)

## 准备免费离线模型

默认 **Hy-MT2 1.8B Q4**，免费、免注册、CPU 离线直译。首次模型约 1.13 GB，网页访问者不下载模型；翻译进程按需启动、完成后退出。

```powershell
.\.venv\Scripts\python.exe lab.py setup-translation
.\.venv\Scripts\python.exe lab.py process --backend hymt
```

自动安装支持 Windows / Linux x64；下载内容固定版本并校验 SHA-256，存放在 `.models/hy-mt/`，不提交仓库。许可与来源：[Hy-MT2](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF)、[llama.cpp](https://github.com/ggml-org/llama.cpp)。

## 缓存、校订与后端

原文始终保留，校订按原文指纹匹配，原文改变后旧校订失效。机器翻译仍可能误解省略主语和梗，不等同于专业人工审校。`auto` 按 HY-MT → Google 尝试，免费在线接口可能限流；其他后端只在明确选择时使用。`--backend none` 仅读取已有缓存。

`--backend hymt` 优先复用匹配原文的完整缓存，包括其他后端已有的译文；不因每日运行而重翻旧内容。
缺译字段才送入模型，相同原文去重；原文变更后新增对应译文，旧缓存不删除。所有内容命中缓存时不启动模型。
人工校订优先，且必须匹配当前原文；失败或空译文不覆盖有效缓存，缺失部分下次继续尝试。

## GitHub Actions

HANE-LAB 的每日任务会准备固定版本的 Hy-MT CPU 模型并运行补译，不需要翻译 API key。
模型和运行包用 Actions 缓存加速，每次先校验；译文和校订保存在归档 `data/` 中，随采集结果提交。
网站与离线包构建仍使用 `--backend none`，只消费已经保存的译文。调度与失败恢复见[部署说明](DEPLOY.md#每日自动采集)。

已准备模型后，可以显式运行隔离的真实模型检查：

```powershell
.\.venv\Scripts\python.exe -X utf8 dev/check_translation_runtime.py
```

它用虚构日文检查新增、缓存复用和原文变更，输出实际耗时；不读取或修改真实归档。
云端手动运行每日任务并勾选 `verify_translation` 可执行同一检查，在 Actions 摘要中查看耗时。
