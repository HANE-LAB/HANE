"""Small shared helpers: paths, json io, logging, config."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

RAW_FILE = DATA / "raw_items.json"        # id -> {"item": <B站原始数据>, "first_seen", "last_seen"}
STATE_FILE = DATA / "state.json"          # 上次全量时间、最新动态 id 等
POSTS_FILE = DATA / "posts.json"          # 规整后的动态（含翻译和分析结果）
TR_CACHE_FILE = DATA / "translations.json"  # 分段翻译缓存：{backend: {原文段: 译文}}
LLM_CACHE_FILE = DATA / "llm_notes.json"    # 大模型分析缓存：{id: {...}}
TR_REVIEW_FILE = DATA / "translation_review.json"  # 按原文哈希绑定的校订，不被机器缓存覆盖
HISTORY_FILE = DATA / "history.jsonl"     # 每次运行追加一行：粉丝数、动态总数
RUNLOG_FILE = ROOT / "logs" / "runs.jsonl"  # 本机运行诊断，不提交归档仓库
SNAPSHOTS = DATA / "snapshots"
METRICS = DATA / "metrics"
MEDIA = DATA / "media"
MEDIA_FILE = DATA / "media.json"

DEFAULTS = {
    "target": {"uid": 2094031249, "name": "火羽ひのめ"},
    "bilibili": {
        "sessdata": "",
        "buvid3": "",
        "fetcher": "auto",
        "page_sleep": [1.5, 3.5],
        "refresh_days": 30,
        "full_refresh_days": 7,
    },
    "translate": {
        "backend": "hymt",
        "translate_forward_origin": True,
        "ollama": {"host": "http://localhost:11434", "model": "qwen2.5:7b"},
        "deepl": {"api_key": ""},
        "claude": {"api_key": "", "model": "claude-haiku-5-5"},
    },
    "analysis": {"llm": "auto"},
    "output": {"open_browser": True, "edition": "release"},
    "archive": {"download_images": True},
    "live": {"enabled": True},
}

# ── terminal output ──────────────────────────────────────────
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def stage(name: str, msg: str = "") -> None:
    print(_c("1;33", f"\n▌{name}") + (f"  {msg}" if msg else ""), flush=True)


def log(msg: str) -> None:
    print("  " + msg, flush=True)


def ok(msg: str) -> None:
    print("  " + _c("32", "✓ ") + msg, flush=True)


def warn(msg: str) -> None:
    print("  " + _c("33", "! ") + msg, flush=True)


def err(msg: str) -> None:
    print("  " + _c("31", "✗ ") + msg, flush=True)


# ── io ───────────────────────────────────────────────────────
def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} 损坏；保留原文件并停止，禁止用空数据覆盖存档") from e


def save_json(path: Path, obj, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1 if pretty else None, separators=None if pretty else (",", ":"))
        f.flush()
        os.fsync(f.fileno())
    # Windows readers/antivirus may briefly hold the destination without delete sharing.
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.05 * 2 ** attempt)


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve a torn final line after power loss, without joining the next observation onto it.
    if path.exists() and path.stat().st_size:
        with open(path, "rb+") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.seek(0, 2)
                f.write(b"\n")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def data_lock():
    """OS releases this lock even when a process crashes."""
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / ".lock", "a+b") as f:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError("已有一个更新/处理进程正在使用 data/，请等它结束后再运行") from e
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def read_jsonl(path: Path) -> list:
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        warn(f"{path.name}:{number} 存在不完整记录，原文已保留，请从备份复核")
    except FileNotFoundError:
        pass
    return out


def jitter_sleep(rng) -> None:
    lo, hi = (rng if isinstance(rng, (list, tuple)) else (rng, rng))
    time.sleep(random.uniform(float(lo), float(hi)))


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


CONFIG_FILE = ROOT / "config.toml"          # 公共设置，会被 git 提交：不要在这里填 Cookie / API key
LOCAL_CONFIG_FILE = ROOT / "config.local.toml"  # 只留在本机的设置（.gitignore 已忽略），值会覆盖 config.toml

# 配置文件里没填时，用这些环境变量补上（GitHub Actions 里由 Secrets 传入）
ENV_FALLBACKS = (
    ("BILI_SESSDATA", ("bilibili", "sessdata")),
    ("BILI_BUVID3", ("bilibili", "buvid3")),
    ("DEEPL_API_KEY", ("translate", "deepl", "api_key")),
    ("ANTHROPIC_API_KEY", ("translate", "claude", "api_key")),
)
SECRET_KEYS = (("bilibili", "sessdata"), ("translate", "deepl", "api_key"), ("translate", "claude", "api_key"))


def _dig(d: dict, keys: tuple):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_FILE
    shared = _read_toml(path)
    cfg = _merge(DEFAULTS, shared)
    if path == CONFIG_FILE:
        cfg = _merge(cfg, _read_toml(LOCAL_CONFIG_FILE))
    for env, keys in ENV_FALLBACKS:
        v = os.environ.get(env, "").strip()
        if v and not _dig(cfg, keys):
            _dig(cfg, keys[:-1])[keys[-1]] = v
    # 记下哪些密钥写在了会被提交的 config.toml 里，命令行据此提醒
    cfg["_secrets_in_shared"] = [".".join(k) for k in SECRET_KEYS if _dig(shared, k)]
    return cfg


def now() -> int:
    return int(time.time())
