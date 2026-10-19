"""Stage 3 · TRANSLATE —— 日文（及其他外语）→ 简体中文。

免费优先，可切换：
  hymt      : 默认，Hy-MT2 量化模型，免费、免注册、CPU 离线直译
  google    : 谷歌翻译免费接口（不用注册，需能访问谷歌）
  ollama    : 本地大模型（免费、离线、更自然；推荐 qwen2.5:7b）
  deepl     : DeepL API（免费 key：每月 50 万字符）
  claude    : Anthropic Claude API（付费）

机器翻译（google/deepl）按「行 + 受保护片段」切分后翻译：
表情 [doge]、@某人、#话题#、链接、BV 号原样保留，不会被翻坏。
大模型（ollama/claude）整条翻译，并顺带输出标签/情绪/摘要（见 analyze.py）。
所有结果按原文片段缓存，重复跑只翻新内容。
"""
from __future__ import annotations

import html as _html
import hashlib
import json
import re
import time

from .util import TR_CACHE_FILE, LLM_CACHE_FILE, TR_REVIEW_FILE, load_json, save_json, log, ok, warn

KANA = re.compile(r"[぀-ゟ゠-ヿㇰ-ㇿｦ-ﾟ]")
HAN = re.compile(r"[一-鿿㐀-䶿]")
LATIN = re.compile(r"[A-Za-z]{3,}")
PROTECT = re.compile(
    r"(\[[^\[\]\n]{1,24}\]"            # B站表情 [doge]
    r"|@[^\s@#\[\]]{1,32}"             # @某人
    r"|#[^#\n]{1,40}#"                 # #话题#
    r"|https?://\S+"                   # 链接
    r"|BV[0-9A-Za-z]{10}"              # BV 号
    r"|[\U0001F000-\U0001FAFF☀-➿️‍]+)"  # emoji 串
)

LLM_TAGS = ["直播预告", "开播", "视频投稿", "歌/音乐", "游戏", "感谢/里程碑", "生日/纪念",
            "周边/商品", "联动", "活动/企划", "日常/杂谈", "转发"]
LLM_MOODS = ["开心", "兴奋", "感动", "平静", "调侃", "疲惫", "低落"]


# 简体中文不用的日式/繁体字形：没有假名但出现这些字，也按日文处理（如「配信開始」）。繁体中文被误判也无妨，照样会转成简体
JP_ONLY = re.compile("[様気戦円図読売続実発変済広応対県駅歩隣険験権覧拡雑単姫価値悩壊浜鉄検稲桜涙満楽転届枠開関説動見話時間語記書長東車門後鳴聴]")


def detect_lang(text: str) -> str:
    """粗略语言判断：含假名或日式汉字→ja；其余汉字→zh；有成段拉丁字母→en；否则 none。"""
    t = PROTECT.sub("", text or "")
    if not t.strip():
        return "none"
    if KANA.search(t) or JP_ONLY.search(t):
        return "ja"
    if HAN.search(t):
        return "zh"
    if LATIN.search(t):
        return "en"
    return "none"


def needs_translation(text: str) -> bool:
    return detect_lang(text) in ("ja", "en")


def split_segments(text: str):
    """切成 [(是否需要翻译, 片段)]。按行切，再把受保护的片段单独拎出来。"""
    out = []
    for i, line in enumerate((text or "").split("\n")):
        if i:
            out.append((False, "\n"))
        pos = 0
        for m in PROTECT.finditer(line):
            if m.start() > pos:
                out.append((True, line[pos:m.start()]))
            out.append((False, m.group(0)))
            pos = m.end()
        if pos < len(line):
            out.append((True, line[pos:]))
    # 只含空白/标点的片段不翻
    return [(flag and bool(re.search(r"\w", seg)), seg) for flag, seg in out]


def to_markup(line: str, wrap: tuple) -> str:
    """把受保护片段包进不翻译标签，其余部分做 HTML 转义。整行一起翻，语序不会被打断。"""
    out, pos = [], 0
    for m in PROTECT.finditer(line):
        out.append(_html.escape(line[pos:m.start()], quote=False))
        out.append(wrap[0] + _html.escape(m.group(0), quote=False) + wrap[1])
        pos = m.end()
    out.append(_html.escape(line[pos:], quote=False))
    return "".join(out)


def from_markup(s: str) -> str:
    return _html.unescape(re.sub(r"</?(?:span|x)\b[^>]*>", "", s or ""))


# ── 后端们 ───────────────────────────────────────────────────
class Backend:
    name = "base"
    is_llm = False
    unit = "line"      # line：整行送翻（后端支持「不翻译标签」）；segment：切掉受保护片段后分段送翻
    batch_size = 50
    max_chars = 4500

    def __init__(self, cfg: dict):
        import requests
        self.cfg = cfg
        self.http = requests.Session()
        self.http.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                           "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0")

    def available(self) -> tuple[bool, str]:
        return True, ""

    def translate_batch(self, texts: list[str]) -> list[str]:
        raise NotImplementedError

    def close(self):
        pass


def document_chunks(text, limit=1200):
    """通常整条翻；长字段优先在换行或句末断开，所有原文字符仍被保留。"""
    while len(text) > limit:
        cuts = list(re.finditer(r"\n+|[。！？!?](?:\s+|$)", text[:limit]))
        end = cuts[-1].end() if cuts else limit
        for match in PROTECT.finditer(text):
            if match.start() < end < match.end():
                end = match.start() or match.end()
                break
        yield text[:end]
        text = text[end:]
    if text:
        yield text


class HYMT(Backend):
    name = "hymt2"
    unit = "document"
    batch_size = 8

    def __init__(self, cfg):
        super().__init__(cfg)
        self.engine = None

    def available(self):
        from .local_mt import executable, MODEL_DIR, MODEL_NAME
        ready = executable() is not None and (MODEL_DIR / MODEL_NAME).is_file()
        return ready, "免费离线日中直译 · Hy-MT2 Q4" if ready else "先运行 python lab.py setup-translation（首次下载约 1.13 GB）"

    def translate_batch(self, texts):
        from .local_mt import Translator
        if self.engine is None:
            self.engine = Translator()
        results = []
        for text in texts:
            try:
                results.append(self.engine.translate(text))
            except Exception as e:
                warn(f"一条直译失败，保留原文：{e}")
                results.append("")
        return results

    def close(self):
        if self.engine is not None:
            self.engine.close(); self.engine = None



class Google(Backend):
    name = "google"
    unit = "segment"
    batch_size = 1

    def available(self):
        try:
            return (True, "") if self.translate_batch(["テスト"])[0] else (False, "谷歌返回为空")
        except Exception as e:
            return False, f"连不上谷歌翻译：{e}"

    def translate_batch(self, texts):
        out = []
        for t in texts:
            r = self.http.get("https://translate.googleapis.com/translate_a/single",
                              params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": t},
                              timeout=20)
            r.raise_for_status()
            out.append("".join(seg[0] for seg in (r.json()[0] or []) if seg and seg[0]))
            time.sleep(0.25)
        return out


class DeepL(Backend):
    name = "deepl"
    batch_size = 50

    def _base(self):
        key = self.cfg["deepl"].get("api_key", "")
        return ("https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com"), key

    def available(self):
        base, key = self._base()
        if not key:
            return False, "config.toml 里没填 deepl api_key"
        try:
            r = self.http.get(f"{base}/v2/usage", headers={"Authorization": f"DeepL-Auth-Key {key}"}, timeout=15)
            r.raise_for_status()
            u = r.json()
            return True, f"本月已用 {u.get('character_count')}/{u.get('character_limit')} 字符"
        except Exception as e:
            return False, f"DeepL 不可用：{e}"

    def translate_batch(self, texts):
        base, key = self._base()
        r = self.http.post(f"{base}/v2/translate", headers={"Authorization": f"DeepL-Auth-Key {key}"},
                           json={"text": [to_markup(t, ("<x>", "</x>")) for t in texts], "target_lang": "ZH-HANS",
                                 "tag_handling": "xml", "ignore_tags": ["x"]}, timeout=30)
        r.raise_for_status()
        return [from_markup(t["text"]) for t in r.json()["translations"]]


LLM_SYSTEM = (
    "你是专业的日中翻译，擅长虚拟主播（VTuber）圈的口语、网络用语和梗。"
    "把用户给的 B 站动态翻译成自然流畅的简体中文：保留语气和颜文字；"
    "[xxx] 形式的表情、@用户名、#话题#、链接、BV号 原样保留；人名和专有名词不确定时保留原文。"
    "然后给这条动态做分析。只输出一个 JSON 对象，不要任何其他文字。"
)


def llm_prompt(text: str, title: str = "", rtype: str = "") -> str:
    return (
        f"动态类型：{rtype or '未知'}\n"
        + (f"标题：{title}\n" if title else "")
        + f"正文：\n{text}\n\n"
        "输出 JSON，字段：\n"
        '  "zh": 正文的中文翻译（正文本来就是中文就原样输出）\n'
        + ('  "title_zh": 标题的中文翻译\n' if title else "")
        + f'  "tags": 从 {json.dumps(LLM_TAGS, ensure_ascii=False)} 里选 1~3 个\n'
        f'  "mood": 从 {json.dumps(LLM_MOODS, ensure_ascii=False)} 里选 1 个\n'
        '  "summary": 不超过 20 个字的中文一句话概括\n'
    )


def parse_llm_json(s: str) -> dict:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("模型没有返回 JSON")
    d = json.loads(m.group(0))
    d["tags"] = [t for t in (d.get("tags") or []) if t in LLM_TAGS][:3]
    if d.get("mood") not in LLM_MOODS:
        d["mood"] = ""
    return d


class Ollama(Backend):
    name = "ollama"
    is_llm = True

    def available(self):
        host = self.cfg["ollama"]["host"].rstrip("/")
        model = self.cfg["ollama"]["model"]
        try:
            r = self.http.get(f"{host}/api/tags", timeout=4)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return False, f"本机没运行 Ollama（{host}）"
        if not any(n == model or n.split(":")[0] == model or n == f"{model}:latest" for n in names):
            return False, f"Ollama 里没有模型 {model}，先执行：ollama pull {model}"
        return True, model

    def chat_json(self, prompt: str) -> dict:
        host = self.cfg["ollama"]["host"].rstrip("/")
        r = self.http.post(f"{host}/api/chat", json={
            "model": self.cfg["ollama"]["model"], "stream": False, "format": "json",
            "options": {"temperature": 0.2, "num_ctx": 4096},
            "messages": [{"role": "system", "content": LLM_SYSTEM}, {"role": "user", "content": prompt}],
        }, timeout=300)
        r.raise_for_status()
        return parse_llm_json(r.json()["message"]["content"])

    def translate_batch(self, texts):
        return [self.chat_json(llm_prompt(t)).get("zh", "") for t in texts]


class Claude(Backend):
    name = "claude"
    is_llm = True

    def available(self):
        if not self.cfg["claude"].get("api_key"):
            return False, "没填 claude api_key（或环境变量 ANTHROPIC_API_KEY）"
        return True, self.cfg["claude"].get("model", "")

    def chat_json(self, prompt: str) -> dict:
        r = self.http.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": self.cfg["claude"]["api_key"], "anthropic-version": "2023-06-01",
            "content-type": "application/json"}, json={
            "model": self.cfg["claude"].get("model") or "claude-haiku-5-5", "max_tokens": 1500,
            "system": LLM_SYSTEM, "messages": [{"role": "user", "content": prompt}]}, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"Claude API {r.status_code}: {r.text[:200]}")
        content = r.json().get("content") or []
        return parse_llm_json("".join(c.get("text", "") for c in content if c.get("type") == "text"))

    def translate_batch(self, texts):
        return [self.chat_json(llm_prompt(t)).get("zh", "") for t in texts]


class Echo(Backend):
    """测试用：不联网，原样加前缀。"""
    name = "echo"

    def translate_batch(self, texts):
        return ["〔译〕" + t for t in texts]


BACKENDS = {"hymt": HYMT, "hymt2": HYMT, "google": Google, "deepl": DeepL, "ollama": Ollama,
            "claude": Claude, "echo": Echo}
AUTO_ORDER = ["hymt", "google"]
# 保留已退役后端的质量标记，以便继续读取旧译文缓存，避免降级覆盖。
QUALITY = {"reviewed": 100, "claude": 5, "ollama": 4, "deepl": 3, "hymt2": 2.7, "hymt": 2.5, "microsoft": 2, "google": 1, "argos": 0.5, "echo": 0}


def pick_backend(cfg: dict, name: str | None = None):
    tcfg = cfg["translate"]
    name = (name or tcfg.get("backend") or "auto").lower()
    if name == "none":
        return None
    order = AUTO_ORDER if name == "auto" else [name]
    for n in order:
        if n not in BACKENDS:
            warn(f"未知翻译后端：{n}")
            continue
        b = BACKENDS[n](tcfg)
        good, info = b.available()
        if good:
            ok(f"翻译后端：{n}" + (f"（{info}）" if info else ""))
            return b
        warn(f"{n} 不可用：{info}")
    return None


# ── 主流程 ───────────────────────────────────────────────────
def _fields(rec: dict, with_orig: bool):
    """一条动态里需要翻译的字段：(字段名, 原文)。"""
    out = [("zh", rec.get("text") or ""), ("title_zh", rec.get("title") or "")]
    if with_orig and rec.get("orig"):
        out.append(("orig_zh", rec["orig"].get("text") or ""))
    return [(k, v) for k, v in out if v and needs_translation(v)]


def translate_posts(posts: list, cfg: dict, backend_name: str | None = None, llm_cache: dict | None = None) -> dict:
    """校订只匹配同一版本原文；先跳过完整校订，最后覆盖部分校订字段。"""
    reviews = load_json(TR_REVIEW_FILE, {})
    with_orig = bool(cfg["translate"].get("translate_forward_origin", True))
    valid, pending = {}, []
    for r in posts:
        r.pop("review_stale", None)
        r.pop("reviewed_fields", None)
        r["lang"] = detect_lang((r.get("title") or "") + "\n" + (r.get("text") or ""))
        note = reviews.get(r["id"], {})
        if note and note.get("source_hash") == source_hash(r):
            fields = {k: note[k] for k in ("zh", "title_zh", "orig_zh") if isinstance(note.get(k), str) and note[k].strip()}
            valid[r["id"]] = fields
            if fields and all(k in fields for k, _ in _fields(r, with_orig)):
                continue
        elif note:
            r["review_stale"] = True
        pending.append(r)
    stats = _translate_posts(pending, cfg, backend_name, llm_cache)
    for r in posts:
        fields = valid.get(r["id"])
        if fields:
            r.update(fields)
            r["reviewed_fields"] = list(fields)
            if all(k in fields for k, _ in _fields(r, with_orig)):
                r["tr"] = "reviewed"
    stats["reviewed"] = sum(r.get("tr") == "reviewed" for r in posts)
    stats["need"] += len(posts) - len(pending)
    if stats["reviewed"] and not stats["backend"]:
        stats["backend"] = "reviewed"
    return stats


def _translate_posts(posts: list, cfg: dict, backend_name: str | None = None, llm_cache: dict | None = None) -> dict:
    """就地给 posts 填上 lang/zh/title_zh/orig_zh/tr。返回统计。"""
    with_orig = bool(cfg["translate"].get("translate_forward_origin", True))
    for r in posts:
        r["lang"] = detect_lang((r.get("title") or "") + "\n" + (r.get("text") or ""))

    todo = [r for r in posts if _fields(r, with_orig)]
    stats = {"need": len(todo), "done": 0, "failed": 0, "cached": 0, "backend": None}
    if not todo:
        ok("没有需要翻译的内容")
        return stats

    cache = load_json(TR_CACHE_FILE, {})
    all_notes = llm_cache if llm_cache is not None else load_json(LLM_CACHE_FILE, {})
    if (backend_name or cfg["translate"].get("backend", "auto")) in ("auto", "none"):
        for r in todo:
            _apply_from_any_cache(r, with_orig, all_notes, cache)
        stats["cached"] = sum(bool(r.get("tr")) for r in todo)
        if stats["cached"] == len(todo) and ((backend_name or cfg["translate"].get("backend")) == "none" or not any(r.get("tr") in ("argos", "hymt") for r in todo)):
            stats["backend"] = "cache"
            return stats
    b = pick_backend(cfg, backend_name)
    if b is None:
        warn("没有可用的翻译后端，本次跳过翻译（页面会显示原文）")
        for r in todo:
            _apply_from_any_cache(r, with_orig, all_notes, cache)
        stats["failed"] = sum(not bool(r.get("tr")) for r in todo)
        return stats
    stats["backend"] = b.name
    bc = cache.setdefault(b.name, {})

    if b.is_llm:
        llm_cache = llm_cache if llm_cache is not None else {}
        pending = [r for r in todo if not _llm_done(r, llm_cache, with_orig)]
        stats["cached"] = len(todo) - len(pending)
        log(f"{len(todo)} 条需要翻译，{stats['cached']} 条已有缓存，本次处理 {len(pending)} 条（大模型逐条）")
        t0 = time.time()
        for i, r in enumerate(pending, 1):
            try:
                note = b.chat_json(llm_prompt(r.get("text") or "", r.get("title") or "", r.get("type") or ""))
                if with_orig and r.get("orig") and needs_translation(r["orig"].get("text") or ""):
                    note["orig_zh"] = b.chat_json(llm_prompt(r["orig"]["text"])).get("zh", "")
                note["backend"] = b.name
                note["source_hash"] = source_hash(r)
                from .util import now, DATA
                note["ts"] = now()
                if not all(note.get(k) for k, _ in _fields(r, with_orig)):
                    raise ValueError("模型返回的翻译字段不完整")
                old = llm_cache.get(r["id"])
                if old:
                    digest = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
                    save_json(DATA / "translation_versions" / r["id"] / f"{digest}.json", old)
                llm_cache[r["id"]] = note
                save_json(LLM_CACHE_FILE, llm_cache)
                stats["done"] += 1
            except Exception as e:
                stats["failed"] += 1
                warn(f"{r['id']} 翻译失败：{e}")
            if i % 10 == 0 or i == len(pending):
                eta = (time.time() - t0) / i * (len(pending) - i)
                log(f"  {i}/{len(pending)}  预计还需 {int(eta)}s")
                save_json(LLM_CACHE_FILE, llm_cache)
        for r in todo:
            n = llm_cache.get(r["id"])
            if _llm_done(r, llm_cache, with_orig):
                r["zh"] = n.get("zh") or ""
                if n.get("title_zh"):
                    r["title_zh"] = n["title_zh"]
                if n.get("orig_zh"):
                    r["orig_zh"] = n["orig_zh"]
                r["tr"] = n.get("backend", b.name)
            else:
                _apply_from_any_cache(r, with_orig, all_notes, cache)
        ok(f"翻译完成：新翻 {stats['done']} 条，失败 {stats['failed']} 条")
        return stats

    # 已有更高质量译文（大模型，或排名更高的机器翻译）完整覆盖的动态：直接用，不重翻
    notes_all, mine = load_json(LLM_CACHE_FILE, {}), QUALITY.get(b.name, 0)
    kept = {r["id"] for r in todo if _apply_better(r, with_orig, mine, notes_all, cache)}
    if kept:
        log(f"{len(kept)} 条已有比 {b.name} 更好的译文，保留不重翻")
        todo = [r for r in todo if r["id"] not in kept]

    # 机器翻译：收集所有待翻片段 → 去重 → 分批 → 回填
    segs = []
    for r in todo:
        for _, txt in _fields(r, with_orig):
            if b.unit == "document":
                if txt not in bc:
                    segs.append(txt)
            elif b.unit == "line":
                segs += [ln for ln in txt.split("\n") if ln.strip() and ln not in bc and needs_translation(ln)]
            else:
                segs += [s for flag, s in split_segments(txt) if flag and s.strip() and s not in bc and needs_translation(s)]
    segs = list(dict.fromkeys(segs))
    stats["segments"] = len(segs)
    log(f"{len(todo)} 条需要翻译 · 新片段 {len(segs)} 个（其余命中缓存）")
    batch, size, done_segs = [], 0, 0

    def flush():
        nonlocal batch, size, done_segs
        if not batch:
            return
        for attempt in range(3):
            try:
                res = b.translate_batch(batch)
                if len(res) != len(batch):
                    raise ValueError("翻译返回数量不匹配，不写入缓存")
                for src, dst in zip(batch, res):
                    if isinstance(dst, str) and dst.strip():
                        bc[src] = dst
                        done_segs += 1
                    else:
                        stats["failed"] += 1
                        warn("一个片段返回空译文，保留原文并标记待复核")
                break
            except Exception as e:
                if attempt == 2:
                    stats["failed"] += len(batch)
                    warn(f"一批 {len(batch)} 个片段翻译失败：{e}")
                else:
                    time.sleep(3 * (attempt + 1))
        batch, size = [], 0
        save_json(TR_CACHE_FILE, cache)
        log(f"  已翻 {done_segs}/{len(segs)} 片段")
        time.sleep(0.6)

    try:
        for s in segs:
            if batch and (len(batch) >= b.batch_size or size + len(s) > b.max_chars):
                flush()
            batch.append(s)
            size += len(s)
        flush()
    finally:
        b.close()

    for r in todo:
        complete = all(_covered(txt, bc) for _, txt in _fields(r, with_orig))
        for key, txt in _fields(r, with_orig):
            if _covered(txt, bc):
                r[key] = assemble(txt, bc)
        if complete:
            r["tr"] = b.name
    stats["done"] = sum(bool(r.get("tr")) for r in todo)
    save_json(TR_CACHE_FILE, cache)
    ok(f"翻译完成（{b.name}）" + (f"，{stats['failed']} 个片段失败，下次会重试" if stats["failed"] else ""))
    return stats


def assemble(text: str, seg_cache: dict) -> str:
    """优先用整行译文；没有整行的再按片段拼。"""
    if text in seg_cache:
        return (seg_cache[text] or "").strip() or text
    lines = (text or "").split("\n")
    if len(lines) > 1:
        return "\n".join(assemble(ln, seg_cache) for ln in lines)
    out = []
    for flag, s in split_segments(text):
        if flag and needs_translation(s):
            core = s.strip()
            lead, trail = s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):]
            out.append(lead + (seg_cache.get(s) or seg_cache.get(core) or core).strip() + trail)
        else:
            out.append(s)
    return "".join(out)


def source_hash(r):
    source = [r.get("text"), r.get("title"), r.get("type"), (r.get("orig") or {}).get("text")]
    return hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest()


def _llm_done(r, llm_cache, with_orig):
    n = llm_cache.get(r["id"])
    if not n or n.get("source_hash") != source_hash(r):
        return False
    return all(bool(n.get(k)) for k, _ in _fields(r, with_orig))


def _covered(text: str, bc: dict) -> bool:
    return bool(bc.get(text)) or all(bool(bc.get(ln)) or (not needs_translation(ln)) or
               all((not f) or bool(bc.get(s)) or (not needs_translation(s)) for f, s in split_segments(ln))
               for ln in text.split("\n"))


def _apply_better(r, with_orig, my_rank, notes_all, tr_cache) -> bool:
    """如果有比当前后端更好的译文能完整覆盖这条动态，就填上并返回 True。"""
    n = notes_all.get(r["id"])
    if n and n.get("zh") and QUALITY.get(n.get("backend"), 4) > my_rank and _llm_done(r, notes_all, with_orig):
        r["zh"] = n["zh"]
        if n.get("title_zh"):
            r["title_zh"] = n["title_zh"]
        if n.get("orig_zh"):
            r["orig_zh"] = n["orig_zh"]
        r["tr"] = n.get("backend", "llm")
        return True
    fields = _fields(r, with_orig)
    for name, bc in sorted(tr_cache.items(), key=lambda kv: -QUALITY.get(kv[0], 0)):
        if QUALITY.get(name, 0) > my_rank and fields and all(_covered(t, bc) for _, t in fields):
            for key, t in fields:
                r[key] = assemble(t, bc)
            r["tr"] = name
            return True
    return False


def _apply_from_any_cache(r, with_orig, notes=None, cache=None):
    """当前后端不可用时，尽量用之前任何后端的缓存把译文补上（优先质量高的）。"""
    llm = (notes if notes is not None else load_json(LLM_CACHE_FILE, {})).get(r["id"])
    if _llm_done(r, {r["id"]: llm}, with_orig):
        r["zh"] = llm["zh"]
        r["title_zh"] = llm.get("title_zh", r.get("title_zh", ""))
        r["orig_zh"] = llm.get("orig_zh", r.get("orig_zh", ""))
        r["tr"] = llm.get("backend", "llm")
        return
    cache = cache if cache is not None else load_json(TR_CACHE_FILE, {})
    for name, bc in sorted(cache.items(), key=lambda kv: -QUALITY.get(kv[0], 0)):
        fields = _fields(r, with_orig)
        if fields and all(_covered(t, bc) for _, t in fields):
            for key, t in fields:
                r[key] = assemble(t, bc)
            r["tr"] = name
            return


def qa_flags(r: dict) -> list:
    """「审阅者」：给译文做几项自动检查，有问题就标记待复核。"""
    flags = []
    if r.get("review_stale"):
        flags.append("原文已变更，旧校订未套用")
    if r.get("tr") == "argos":
        flags.append("离线转译需复核")
    src, zh = r.get("text") or "", r.get("zh") or ""
    if not zh and needs_translation(src):
        flags.append("未翻译")
        return flags
    if zh:
        if re.search(r"[가-힣]", zh) and not re.search(r"[가-힣]", src):
            flags.append("译文混入其他语言")
        if re.search(r"(?:^|\n).{1,18} 翻译成 .{1,25}(?:\n|$)|将以下文本翻译为|参考下面的翻译", zh) and "翻译" not in src:
            flags.append("译文疑似混入提示词")
        protected = [m.group().strip("\u200d\ufe0f") for m in PROTECT.finditer(src)]
        if any(token and token not in zh for token in protected):
            flags.append("表情/链接/提及需复核")
        if any(m.group() not in src for m in re.finditer(r"(.{2,16})\1{3,}", PROTECT.sub("", zh))):
            flags.append("译文异常重复")
        left = KANA.findall(PROTECT.sub("", zh))
        if len(left) >= 4 and "zh" not in r.get("reviewed_fields", []):
            flags.append("译文残留假名")
        ls, lz = len(PROTECT.sub("", src)), len(PROTECT.sub("", zh))
        if ls >= 20 and lz < ls * 0.25:
            flags.append("译文过短")
        if ls >= 10 and lz > ls * 3.5:
            flags.append("译文过长")
    return flags
