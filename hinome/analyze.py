"""Stage 4 · ANALYZE —— 给每条动态打标签、抽关键词，并做译文自检。

免费部分（总是运行）：
  · 规则标签：按动作/类型 + 中日关键词归类（直播预告、开播、歌、游戏、感谢/里程碑……）
  · 关键词：中文用 jieba，日文用 janome（都是纯 Python，没装就跳过）
  · 互动、表情、@联动、话题等结构化信息（normalize 阶段已抽好）
大模型部分（翻译后端是 ollama/claude 时）：标签、情绪、一句话摘要，翻译时一并产出。
"""
from __future__ import annotations

import re

from .translate import qa_flags, PROTECT, LLM_TAGS, source_hash
from .util import log, ok, warn

TIME_RE = re.compile(r"\d{1,2}\s*[:：]\s*\d{2}|\d{1,2}\s*(時|时|点|點)")
WHEN_RE = re.compile(r"今夜|今晩|今日|この後|このあと|明日|あした|今晚|今天晚上|明天|今天")
STREAM_RE = re.compile(r"配信|枠|直播|開始|开始|やります|します|开播|待機|放送")
PREVIEW_KW = ["待機", "予定", "スケジュール", "日程", "周表", "週間予定", "直播预告", "开播预告", "ゲリラ", "告知"]


def is_preview(blob: str) -> bool:
    if any(k in blob for k in PREVIEW_KW):
        return True
    if not STREAM_RE.search(blob):
        return False
    if re.search(r"ありがとう|お疲れ|感谢|谢谢|ありがと", blob) and not TIME_RE.search(blob) and not re.search(r"この後|このあと|今夜|今晩|明日|あした|今晚|明天", blob):
        return False
    return bool(TIME_RE.search(blob) or WHEN_RE.search(blob))


RULES = [
    ("歌/音乐", ["歌", "カバー", "cover", "Cover", "COVER", "オリ曲", "MV", "翻唱", "歌回", "原创曲", "ライブ", "演唱", "カラオケ", "唱"]),
    ("游戏", ["ゲーム", "游戏", "マイクラ", "Minecraft", "APEX", "Apex", "ポケモン", "原神", "スト6", "ホラー", "实况", "攻略", "Steam", "ゲーム実況", "マリカ", "雀魂"]),
    ("感谢/里程碑", ["ありがとう", "感謝", "谢谢", "感谢", "突破", "達成", "达成", "記念", "舰长", "艦長", "提督", "総督", "千舰", "万粉",
                    "フォロワー", "粉丝", "登録者", "お祝い", "おめでとう", "感动", "嬉しい"]),
    ("生日/纪念", ["誕生日", "生日", "周年", "周年", "記念日", "纪念", "バースデー", "birthday", "Birthday", "誕生祭", "生诞"]),
    ("周边/商品", ["グッズ", "周边", "発売", "发售", "販売", "预售", "通販", "限定", "ボイス", "语音", "抱き枕", "アクスタ", "立牌", "签名"]),
    ("联动", ["コラボ", "联动", "連動", "ゲスト", "嘉宾", "凸待ち", "オフコラボ"]),
    ("活动/企划", ["企画", "企划", "イベント", "活动", "抽選", "抽奖", "プレゼント", "参加", "募集", "投票", "比赛", "大会"]),
]


def rule_tags(r: dict) -> list:
    tags = []
    t = r.get("type")
    if t == "live":
        tags.append("开播")
    if t == "video":
        tags.append("视频投稿")
    if t == "forward":
        tags.append("转发")
    blob = " ".join(filter(None, [r.get("text"), r.get("title"), r.get("zh"), r.get("title_zh"),
                                  (r.get("video") or {}).get("title"), (r.get("live") or {}).get("title"),
                                  (r.get("reserve") or {}).get("title")]))
    if r.get("reserve") or (t in ("text", "image") and is_preview(" ".join(filter(None, [r.get("text"), r.get("zh")])))):
        tags.append("直播预告")
    for tag, kws in RULES:
        if tag in tags:
            continue
        if any(k in blob for k in kws):
            tags.append(tag)
    if r.get("mentions") and "联动" not in tags and t != "forward":
        tags.append("联动")
    if not tags or tags == ["转发"]:
        tags.append("日常/杂谈")
    return [x for x in LLM_TAGS if x in tags]


# ── 关键词 ───────────────────────────────────────────────────
ZH_STOP = set("""的 了 是 在 我 你 他 她 它 们 这 那 就 都 也 和 与 及 还 又 很 太 吧 呢 啊 哦 嗯 呀 啦 哈 吗 嘛 么 着 过 被 把 给
让 对 从 到 为 以 而 但 并 或 如果 因为 所以 然后 今天 明天 昨天 大家 各位 一下 一个 一起 什么 怎么 这个 那个 这样 我们 你们
自己 没有 可以 已经 还是 真的 非常 一直 时候 现在 今晚 时间 东西 事情 感觉 觉得 知道 看到 出来 起来 应该 可能 需要 开始 进行
谢谢 感谢 非常感谢 多多 支持 欢迎 请 哔哩哔哩 bilibili 动态 视频 直播 转发 点赞 评论""".split())
JA_STOP = set("""こと もの ため よう これ それ あれ ここ そこ 今日 明日 昨日 みんな 皆さん 皆 私 僕 自分 ところ とき 時 さん ちゃん くん
感じ 気 方 中 後 前 今 本当 ほんと 配信 動画 ありがとう よろしく お願い 宜しく お疲れ様 です ます""".split())

_jieba = _janome = None


def _load_nlp():
    global _jieba, _janome
    if _jieba is None:
        try:
            import logging
            import jieba
            import jieba.analyse  # noqa: F401
            jieba.setLogLevel(logging.WARNING)
            _jieba = jieba
        except ImportError:
            _jieba = False
            warn("未安装 jieba，跳过中文关键词（pip install jieba）")
    if _janome is None:
        try:
            from janome.tokenizer import Tokenizer
            _janome = Tokenizer()
        except ImportError:
            _janome = False
            warn("未安装 janome，跳过日文关键词（pip install janome）")


def _clean(s: str) -> str:
    return PROTECT.sub(" ", s or "")


def kw_zh(text: str, k: int = 8) -> list:
    if not _jieba or not text:
        return []
    import jieba.analyse
    words = jieba.analyse.extract_tags(_clean(text), topK=k * 2, allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "eng", "an"))
    return [w for w in words if w not in ZH_STOP and len(w) > 1 and not w.isdigit()][:k]


def kw_ja(text: str, k: int = 8) -> list:
    if not _janome or not text:
        return []
    out = []
    for tok in _janome.tokenize(_clean(text)):
        pos = tok.part_of_speech.split(",")
        if pos[0] != "名詞" or pos[1] in ("非自立", "代名詞", "数", "接尾", "副詞可能"):
            continue
        w = tok.surface
        if len(w) < 2 or w in JA_STOP or re.fullmatch(r"[\W\d_ー〜~]+", w):
            continue
        if w not in out:
            out.append(w)
        if len(out) >= k:
            break
    return out


def analyze_posts(posts: list, llm_cache: dict) -> dict:
    _load_nlp()
    n_llm = n_flag = 0
    for r in posts:
        r["tags_rule"] = rule_tags(r)
        note = llm_cache.get(r["id"]) or {}
        if note.get("source_hash") != source_hash(r):
            note = {}
        if note.get("tags"):
            r["tags"] = note["tags"]
            r["tags_src"] = "llm"
            n_llm += 1
        else:
            r["tags"] = r["tags_rule"]
            r["tags_src"] = "rule"
        if note.get("mood"):
            r["mood"] = note["mood"]
        if note.get("summary"):
            r["summary"] = note["summary"]

        zh_text = "\n".join(filter(None, [r.get("title_zh") or (r.get("title") if r.get("lang") == "zh" else ""),
                                          r.get("zh") or (r.get("text") if r.get("lang") in ("zh", "none") else "")]))
        r["kw_zh"] = kw_zh(zh_text)
        r["kw_ja"] = kw_ja("\n".join(filter(None, [r.get("title"), r.get("text")]))) if r.get("lang") == "ja" else []
        r["qa"] = qa_flags(r)
        if r["qa"]:
            n_flag += 1
        s = r.get("stats") or {}
        r["score"] = int(s.get("like", 0)) + 3 * int(s.get("comment", 0)) + 5 * int(s.get("forward", 0))
    ok(f"分析完成：{len(posts)} 条 · 大模型标注 {n_llm} 条 · 译文待复核 {n_flag} 条")
    return {"llm_tagged": n_llm, "qa_flagged": n_flag}
