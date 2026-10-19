"""Stage 2 · NORMALIZE —— 把 B 站原始动态结构整理成统一的记录。

B 站 web-dynamic 接口的结构比较深，而且同一种内容会有新旧两种写法
（旧：module_dynamic.desc + major.draw；新 opus 风格：major.opus.summary + pics），这里都兼容。
"""
from __future__ import annotations

import json
import re

TYPE_MAP = {
    "DYNAMIC_TYPE_WORD": "text",
    "DYNAMIC_TYPE_DRAW": "image",
    "DYNAMIC_TYPE_AV": "video",
    "DYNAMIC_TYPE_UGC_SEASON": "video",
    "DYNAMIC_TYPE_PGC": "video",
    "DYNAMIC_TYPE_PGC_UNION": "video",
    "DYNAMIC_TYPE_FORWARD": "forward",
    "DYNAMIC_TYPE_LIVE_RCMD": "live",
    "DYNAMIC_TYPE_LIVE": "live",
    "DYNAMIC_TYPE_ARTICLE": "article",
    "DYNAMIC_TYPE_MUSIC": "music",
    "DYNAMIC_TYPE_COMMON_SQUARE": "other",
    "DYNAMIC_TYPE_COMMON_VERTICAL": "other",
    "DYNAMIC_TYPE_COURSES_SEASON": "other",
    "DYNAMIC_TYPE_NONE": "deleted",
}

EMOTE_RE = re.compile(r"\[[^\[\]\n]{1,24}\]")


def _g(d, *path, default=None):
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and -len(d) <= p < len(d):
            d = d[p]
        else:
            return default
        if d is None:
            return default
    return d


def _num(x) -> int:
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        try:
            if s.endswith("万"):
                return int(float(s[:-1]) * 10000)
            return int(float(s))
        except ValueError:
            return 0
    return 0


def parse_rich(obj, acc: dict) -> str:
    """解析 desc / opus.summary 这类带 rich_text_nodes 的对象，返回纯文本，同时收集 @、话题、表情、链接。"""
    if not isinstance(obj, dict):
        return ""
    nodes = obj.get("rich_text_nodes") or []
    text = obj.get("text")
    parts = []
    for n in nodes:
        t = n.get("type", "")
        s = n.get("orig_text") or n.get("text") or ""
        parts.append(s)
        if t == "RICH_TEXT_NODE_TYPE_AT":
            acc["mentions"].append({"name": (n.get("text") or s).lstrip("@").strip(), "mid": str(n.get("rid") or "")})
        elif t == "RICH_TEXT_NODE_TYPE_TOPIC":
            acc["hashtags"].append(s.strip("#").strip())
        elif t == "RICH_TEXT_NODE_TYPE_EMOJI":
            em = n.get("emoji") or {}
            name = em.get("text") or s
            acc["emotes"].append(name)
            if em.get("icon_url"):
                acc["emote_icons"][name] = em["icon_url"]
        elif t in ("RICH_TEXT_NODE_TYPE_WEB", "RICH_TEXT_NODE_TYPE_BV", "RICH_TEXT_NODE_TYPE_AV",
                   "RICH_TEXT_NODE_TYPE_GOODS", "RICH_TEXT_NODE_TYPE_LOTTERY", "RICH_TEXT_NODE_TYPE_VOTE",
                   "RICH_TEXT_NODE_TYPE_CV", "RICH_TEXT_NODE_TYPE_OGV_SEASON"):
            acc["links"].append({"kind": t.replace("RICH_TEXT_NODE_TYPE_", "").lower(),
                                 "text": n.get("text") or s, "url": _url(n.get("jump_url"))})
    if not text:
        text = "".join(parts)
    if not nodes:  # 没有结构化节点时，至少用正则补表情
        acc["emotes"].extend(EMOTE_RE.findall(text or ""))
    return text or ""


def _url(u):
    if not u:
        return ""
    u = str(u)
    return "https:" + u if u.startswith("//") else u


def _img(u):
    return _url(u)


def _new_acc():
    return {"mentions": [], "hashtags": [], "emotes": [], "links": [], "emote_icons": {}}


def parse_item(item: dict, acc: dict | None = None, depth: int = 0) -> dict:
    acc = acc if acc is not None else _new_acc()
    mods = item.get("modules") or {}
    author = mods.get("module_author") or {}
    dyn = mods.get("module_dynamic") or {}
    major = dyn.get("major") or {}
    mtype = major.get("type", "")
    rtype = item.get("type", "")
    iid = str(item.get("id_str") or "")

    rec = {
        "id": iid,
        "ts": _num(author.get("pub_ts")),
        "url": f"https://t.bilibili.com/{iid}" if iid else "",
        "type": TYPE_MAP.get(rtype, "other"),
        "raw_type": rtype.replace("DYNAMIC_TYPE_", "").lower(),
        "action": author.get("pub_action") or "",
        "author": author.get("name") or "",
        "author_mid": str(author.get("mid") or ""),
        "text": "",
        "title": "",
        "images": [],
        "cover": "",
        "pinned": _g(mods, "module_tag", "text") == "置顶",
        "locked": False,
    }

    texts = [parse_rich(dyn.get("desc"), acc)]

    if mtype == "MAJOR_TYPE_OPUS":
        op = major.get("opus") or {}
        rec["title"] = op.get("title") or ""
        texts.append(parse_rich(op.get("summary"), acc))
        rec["images"] = [_img(p.get("url")) for p in (op.get("pics") or []) if p.get("url")]
        if rec["type"] == "image" and not rec["images"]:
            rec["type"] = "text"
        if op.get("jump_url"):
            rec["url"] = _url(op["jump_url"])
    elif mtype == "MAJOR_TYPE_DRAW":
        rec["images"] = [_img(p.get("src")) for p in (_g(major, "draw", "items") or []) if p.get("src")]
    elif mtype in ("MAJOR_TYPE_ARCHIVE", "MAJOR_TYPE_UGC_SEASON", "MAJOR_TYPE_PGC"):
        a = major.get("archive") or major.get("ugc_season") or major.get("pgc") or {}
        rec["title"] = a.get("title") or ""
        rec["cover"] = _img(a.get("cover"))
        rec["video"] = {
            "bvid": a.get("bvid") or "",
            "title": a.get("title") or "",
            "desc": a.get("desc") or "",
            "duration": a.get("duration_text") or "",
            "play": _num(_g(a, "stat", "play")),
            "danmaku": _num(_g(a, "stat", "danmaku")),
            "url": _url(a.get("jump_url")) or (f"https://www.bilibili.com/video/{a.get('bvid')}" if a.get("bvid") else ""),
        }
    elif mtype == "MAJOR_TYPE_LIVE_RCMD":
        raw = _g(major, "live_rcmd", "content") or "{}"
        try:
            info = (json.loads(raw) if isinstance(raw, str) else raw).get("live_play_info") or {}
        except (ValueError, AttributeError):
            info = {}
        rec["title"] = info.get("title") or ""
        rec["cover"] = _img(info.get("cover"))
        rec["live"] = {"title": info.get("title") or "", "area": info.get("area_name") or "",
                       "start": _num(info.get("live_start_time")), "url": _url(info.get("link")),
                       "watched": _g(info, "watched_show", "text_large") or ""}
    elif mtype == "MAJOR_TYPE_LIVE":
        lv = major.get("live") or {}
        rec["title"] = lv.get("title") or ""
        rec["cover"] = _img(lv.get("cover"))
        rec["live"] = {"title": lv.get("title") or "", "area": lv.get("desc_first") or "",
                       "start": 0, "url": _url(lv.get("jump_url")), "watched": lv.get("desc_second") or ""}
    elif mtype == "MAJOR_TYPE_ARTICLE":
        ar = major.get("article") or {}
        rec["title"] = ar.get("title") or ""
        texts.append(ar.get("desc") or "")
        covers = ar.get("covers") or []
        rec["cover"] = _img(covers[0]) if covers else ""
        rec["article"] = {"title": ar.get("title") or "", "url": _url(ar.get("jump_url"))}
    elif mtype == "MAJOR_TYPE_MUSIC":
        mu = major.get("music") or {}
        rec["title"] = mu.get("title") or ""
        rec["cover"] = _img(mu.get("cover"))
    elif mtype == "MAJOR_TYPE_COMMON":
        cm = major.get("common") or {}
        rec["title"] = cm.get("title") or ""
        texts.append(cm.get("desc") or "")
        rec["cover"] = _img(cm.get("cover"))
    elif mtype in ("MAJOR_TYPE_BLOCKED", "MAJOR_TYPE_UPOWER_COMMON"):
        rec["locked"] = True
        texts.append(_g(major, "blocked", "hint_message") or "（充电专属内容）")
    elif mtype == "MAJOR_TYPE_NONE":
        texts.append(_g(major, "none", "tips") or "")
        if rtype == "DYNAMIC_TYPE_NONE":
            rec["type"] = "deleted"

    # 附加卡片：直播预约 / 投票 / 关联视频
    add = dyn.get("additional") or {}
    at = add.get("type", "")
    if at == "ADDITIONAL_TYPE_RESERVE":
        rv = add.get("reserve") or {}
        rec["reserve"] = {"title": rv.get("title") or "",
                          "desc": " · ".join(x for x in (_g(rv, "desc1", "text"), _g(rv, "desc2", "text")) if x),
                          "url": _url(rv.get("jump_url"))}
    elif at == "ADDITIONAL_TYPE_VOTE":
        rec["vote"] = _g(add, "vote", "desc") or ""
    elif at == "ADDITIONAL_TYPE_UGC":
        rec["related"] = {"title": _g(add, "ugc", "title") or "", "url": _url(_g(add, "ugc", "jump_url"))}

    topic = dyn.get("topic") or {}
    if topic.get("name"):
        acc["hashtags"].append(topic["name"])

    rec["text"] = "\n".join(dict.fromkeys(t.strip() for t in texts if t and t.strip())).strip()
    if rec["type"] == "text" and rec["images"]:
        rec["type"] = "image"

    st = mods.get("module_stat") or {}
    rec["stats"] = {"like": _num(_g(st, "like", "count")), "comment": _num(_g(st, "comment", "count")),
                    "forward": _num(_g(st, "forward", "count"))}

    if depth == 0 and item.get("orig"):
        sub_acc = _new_acc()
        o = parse_item(item["orig"], sub_acc, depth=1)
        acc["emote_icons"].update(sub_acc["emote_icons"])
        rec["orig"] = {k: o.get(k) for k in ("id", "url", "type", "author", "author_mid", "text",
                                             "title", "images", "cover", "ts", "video", "live")
                       if o.get(k) not in (None, "", [])}
    return rec


def normalize(store: dict) -> tuple[list, dict]:
    """store: raw_items.json 的内容。返回 (records, emote_icons)。"""
    out, icons = [], {}
    for iid, wrap in store.items():
        acc = _new_acc()
        try:
            rec = parse_item(wrap.get("item") or {}, acc)
        except Exception as e:  # 单条坏数据不拖垮整条链
            rec = {"id": iid, "ts": 0, "type": "other", "text": "", "parse_error": str(e),
                   "stats": {"like": 0, "comment": 0, "forward": 0}, "images": []}
        rec["mentions"] = _dedupe_dicts(acc["mentions"], "name")
        rec["hashtags"] = sorted(set(h for h in acc["hashtags"] if h))
        rec["emotes"] = acc["emotes"]
        rec["links"] = acc["links"]
        rec["first_seen"] = wrap.get("first_seen")
        rec["last_seen"] = wrap.get("last_seen")
        if wrap.get("gone"):
            rec["gone"] = wrap["gone"]
        icons.update(acc["emote_icons"])
        out.append(rec)
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return out, icons


def _dedupe_dicts(items, key):
    seen, out = set(), []
    for d in items:
        k = d.get(key)
        if k and k not in seen:
            seen.add(k)
            out.append(d)
    return out
