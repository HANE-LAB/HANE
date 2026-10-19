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
