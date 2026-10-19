"""按需启动免费的 HY-MT CPU 翻译；模型、运行包、日志只留在 .models。"""
from __future__ import annotations

import atexit
import hashlib
import os
import platform
import re
import socket
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

from .util import ROOT, log

MODEL_DIR = ROOT / ".models" / "hy-mt"
MODEL_NAME = "Hy-MT2-1.8B-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/a0c709d9fac510f2c807aa3af52872340dc37a4a/" + MODEL_NAME
MODEL_SHA = "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699"
RUNTIMES = {
    "Windows": ("llama-b11429-bin-win-cpu-x64.zip", "1283323272b04cd07905816a597a0da810918102de958f4ff6f7bbaa70ed2efe"),
    "Linux": ("llama-b11429-bin-ubuntu-x64.tar.gz", "f6d25dde8f51133143d1453da4fd5f73b145127177612a283bf7995957af3392"),
}
TERMS = {"配信": "直播", "私信": "私信", "低気圧": "低气压", "狸": "貉", "夏バテ": "暑热疲乏", "ひのめ": "ひのめ",
         "ちいかわ": "吉伊卡哇", "くまモン": "熊本熊", "ドラクエ": "勇者斗恶龙", "エヴァ": "EVA",
         "ビリビリ": "B站", "メンテ": "维护", "ニンテンドーダイレクト": "任天堂直面会", "ガチョウ": "鹅",
         "ハチワレ": "小八", "メガシンカ": "超级进化", "フライゴン": "沙漠蜻蜓",
         "モンハン": "怪物猎人", "ドラえもん": "哆啦A梦", "サーナイト": "沙奈朵", "ハシビロコウ": "鲸头鹳",
         "どうぶつの森": "动物森友会", "パルワールド": "幻兽帕鲁", "光の戦士": "光之战士", "ナギ節": "长草期",
         "アプデ": "更新", "メインクエスト": "主线任务", "シャチ": "虎鲸", "スカイツリー": "晴空塔",
         "返事が来ない": "没收到回复", "ワンピース": "海贼王",
         "スルメイカ": "鱿鱼", "タコとイカ": "章鱼和鱿鱼", "イカ焼き": "烤鱿鱼", "鰐": "鳄鱼", "マグロ": "金枪鱼", "おでん": "关东煮", "カーリング": "冰壶",
         "クレヨンしんちゃん": "蜡笔小新", "泉こなた": "泉此方", "初音ミク": "初音未来", "キャプボ": "视频采集卡",
         "ニンダイ": "任天堂直面会", "ポケモン金銀": "宝可梦 金／银", "メガガルーラ": "超级袋兽",
         "奈須きのこ": "奈须蘑菇", "マツコデラックス": "マツコ・デラックス", "乗艦": "上舰", "艦長": "舰长", "GW": "黄金周",
         "ひのめさん": "ひのめ", "ひの雑": "火羽杂谈", "9万人記念": "九万粉丝纪念", "10万人記念": "十万粉丝纪念"}
PHRASES = {"今日もこの後から配信する": "今天也马上开播！", "今日はこの後から配信する": "今天马上开播！", "配信開始しました": "直播开始了！",
           "今日も22時から配信する": "今天也从22点开始直播！", "今日の配信も22時からやる": "今天的直播也从22点开始！",
           "今日の配信も22時から": "今天的直播也从22点开始！", "今日も22時から配信": "今天也从22点开始直播！",
           "今日の配信は22時から": "今天的直播从22点开始！"}


def prompt(text):
    terms = [f"{src} 翻译成 {dst}" for src, dst in TERMS.items() if src in text]
    glossary = "参考下面的翻译：\n" + "\n".join(terms) + "\n\n" if terms else ""
    context = "下面是一位日本虚拟主播写给观众的动态。省略的主语请结合上下文理解，保留疑问与否定含义。保留全部句子、数字、表情、换行与已有中文，不确定的专名保留原文。\n\n"
    return context + glossary + "将以下文本翻译为简体中文，注意只需要输出翻译后的结果，不要额外解释：\n" + text



def _sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def _download(url, path, digest):
    import requests
    if path.exists() and _sha(path) == digest:
        return
    log(f"下载 {path.name}（固定版本，完成后校验 SHA-256）")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=(20, 90)) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for block in response.iter_content(1024 * 1024): f.write(block)
    if _sha(tmp) != digest:
        raise ValueError(f"{path.name} 校验失败，未启用下载文件")
    tmp.replace(path)


def executable():
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    return next((MODEL_DIR / "runtime").rglob(name), None)


def setup():
    system = platform.system()
    if system not in RUNTIMES or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("自动安装支持 Windows/Linux x64；其他平台可将官方 llama-server 放入 .models/hy-mt/runtime")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    name, digest = RUNTIMES[system]
    archive = MODEL_DIR / name
    _download("https://github.com/ggml-org/llama.cpp/releases/download/b11429/" + name, archive, digest)
    runtime = (MODEL_DIR / "runtime").resolve()
    if system == "Windows":
        with zipfile.ZipFile(archive) as z:
            if any(not (runtime / n).resolve().is_relative_to(runtime) for n in z.namelist()):
                raise ValueError("运行包包含越界路径")
            z.extractall(runtime)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(runtime, filter="data")
            else:  # Python before 3.10.12 / 3.11.4 has no extraction filters: check every member ourselves
                for m in t.getmembers():
                    if not (m.isfile() or m.isdir() or m.issym()) or not (runtime / m.name).resolve().is_relative_to(runtime) \
                            or (m.issym() and not ((runtime / m.name).parent / m.linkname).resolve().is_relative_to(runtime)):
                        raise ValueError("运行包包含越界路径")
                t.extractall(runtime)
    _download(MODEL_URL, MODEL_DIR / MODEL_NAME, MODEL_SHA)
    _download(MODEL_URL.rsplit("/", 1)[0] + "/LICENSE.txt", MODEL_DIR / "HY-MT2-LICENSE.txt",
              "a1d52d448f81c584a47c583e19dfab2d3851c7c84431b07baee093c1113ed114")
    _download("https://raw.githubusercontent.com/ggml-org/llama.cpp/b11429/LICENSE", MODEL_DIR / "llama-LICENSE.txt",
              "94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d")
    log("HY-MT 已就绪：模型约 1.13 GB；CPU 按需翻译，结束后退出，不需要注册或 API Key。")


class Translator:
    def __init__(self):
        self.process = self.output = None
        import requests
        self.http = requests.Session()
        self.http.trust_env = False  # 私有译文不经过系统代理。
        atexit.register(self.close)

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        restart = self.process is not None   # a server that exited mid-run is restarted, a few times at most
        if restart:
            self.restarts = getattr(self, "restarts", 0) + 1
            if self.restarts > 3:
                raise RuntimeError("本地翻译进程反复退出，请查看 .models/hy-mt/runtime.log")
        self.close()
        exe = executable()
        if not exe or not (MODEL_DIR / MODEL_NAME).exists():
            raise RuntimeError("先运行 python lab.py setup-translation")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.output = (MODEL_DIR / "runtime.log").open("a" if restart else "w", encoding="utf-8")
        try:
            self.process = subprocess.Popen([str(exe), "-m", str(MODEL_DIR / MODEL_NAME),
                "--host", "127.0.0.1", "--port", str(port), "-c", "4096", "-np", "1", "-t", "4", "-ngl", "0", "--cache-ram", "0", "--no-webui"],
                stdout=self.output, stderr=self.output, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for _ in range(240):
                if self.process.poll() is not None: raise RuntimeError("本地翻译进程启动失败，请查看 .models/hy-mt/runtime.log")
                try:
                    if self.http.get(self.url + "/health", timeout=1).ok: return
                except Exception: pass
                time.sleep(.25)
            raise TimeoutError("本地翻译模型在 60 秒内未就绪")
        except BaseException:
            self.close()
            raise

    def translate(self, text):
        self.start()
        # 长文按段落/句子分块，禁止用 token 截断悄悄丢掉原文。
        from .translate import document_chunks
        parts = []
        for chunk in (part for paragraph in re.split(r"(\n\s*\n)", text) for part in document_chunks(paragraph)):
            if not chunk.strip():
                parts.append(chunk); continue
            phrase = chunk.strip().strip("\u200b\u200d").rstrip("！!")
            if phrase in PHRASES:
                parts.append(PHRASES[phrase]); continue
            r = self.http.post(self.url + "/v1/chat/completions", json={
                "messages": [{"role": "user", "content": prompt(chunk)}],
                "max_tokens": 2048, "temperature": 0, "repeat_penalty": 1.05}, timeout=180)
            r.raise_for_status()
            choice = r.json()["choices"][0]
            result = choice["message"]["content"].strip()
            if choice.get("finish_reason") != "stop" or not result:
                raise ValueError("译文未完整结束，不写入缓存")
            parts.append(re.match(r"\s*", chunk).group() + result + re.search(r"\s*$", chunk).group())
        return "".join(parts)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=10)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
            self.process = None
        if self.output is not None:
            self.output.close(); self.output = None

