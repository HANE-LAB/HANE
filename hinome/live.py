"""Nailv's public Danmakus source: archive canonical sessions, never infer lives from posts."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from .util import DATA, load_json, save_json, now, ok

SESSIONS_FILE = DATA / "live_sessions.json"
STATE_FILE = DATA / "live_state.json"
SNAPSHOTS = DATA / "live_snapshots"
API = "https://api.ukamnads.icu/api/v2/channel"
SOURCE = "https://stats.nailv.live/streamer/"


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def normalize(item, uid):
    iid = str(UUID(item["liveId"]))
    start = number(item.get("startDate"))
    if start is None or not 946684800000 <= start < 4102444800000:
        raise ValueError(f"直播 {iid} 的开始时间无效")
    stop = number(item.get("stopDate"))
    finished = item.get("isFinish") is True
    end = stop / 1000 if finished and stop is not None and start <= stop < 4102444800000 else None
    income = number(item.get("totalIncome"))
    cents = int((Decimal(str(income)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if income is not None else None
    result = {"id": iid, "uid": uid, "title": str(item.get("title") or "无标题"),
              "start": start / 1000, "end": end, "duration": end - start / 1000 if end is not None else None,
              "finished": finished, "complete": item.get("isFull") if isinstance(item.get("isFull"), bool) else None,
              "merged": item.get("isMerged") is True, "revenue_cents": cents,
              "url": f"{SOURCE}{uid}/stream/{iid}"}
    for dest, src in {"danmaku": "danmakusCount", "watch": "watchCount", "likes": "likeCount",
                      "payers": "payCount", "interactors": "interactionCount", "peak": "maxOnlineCount"}.items():
        result[dest] = number(item.get(src))
    # Older source records use 0 for unavailable high-energy counts; do not plot them as an empty room.
    if result["peak"] == 0:
        result["peak"] = None
    return result


def validate_response(body, uid):
    if not isinstance(body, dict) or body.get("code") != 200:
        raise ValueError("直播来源未返回成功响应")
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("channel"), dict) or not isinstance(data.get("lives"), list):
        raise ValueError("直播来源响应结构不完整")
    channel, lives = data["channel"], data["lives"]
    if str(channel.get("uId")) != str(uid) or not number(channel.get("roomId")):
        raise ValueError("直播来源 UID/房间不匹配，拒绝混入其他主播")
    ids = [normalize(item, uid)["id"] for item in lives]
    if len(set(ids)) != len(ids):
        raise ValueError("直播来源返回重复场次，不能据此统计")
    total = number(channel.get("totalLiveCount"))
    if total is None or total != len(lives):
        raise ValueError("直播场次列表与来源总数不一致，保留旧数据等待重试")
    return channel, lives


def snapshot(uid, iid, item, ts):
    digest = hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = SNAPSHOTS / str(uid) / iid / f"{digest}.json"
    if not path.exists():
        save_json(path, {"ts": ts, "item": item})
    return digest


def ingest(body, uid, ts=None):
    channel, lives = validate_response(body, uid)
    ts = now() if ts is None else ts
    store = load_json(SESSIONS_FILE, {})
    if not lives and any(v.get("uid") == uid for v in store.values()):
        raise ValueError("直播来源突然返回空列表，保留旧归档")
    fresh, changed = 0, 0
    for item in lives:
        iid = str(UUID(item["liveId"]))
        old = store.get(iid)
        if old and old.get("uid") != uid:
            raise ValueError("直播 ID 与其他 UID 冲突，保留旧归档")
        digest = snapshot(uid, iid, item, ts)
        fresh += old is None
        changed += old is not None and old.get("snapshot") != digest
        store[iid] = {"uid": uid, "item": item, "first_seen": old["first_seen"] if old else ts,
                      "last_seen": ts, "snapshot": digest}
    snapshot(uid, "channel", channel, ts)
    save_json(SESSIONS_FILE, store)
    state = {"schema_version": 3, "uid": uid, "source": SOURCE + str(uid), "api": API,
             "last_attempt": ts, "last_success": ts, "last_result": {"status": "ok", "ts": ts},
             "source_count": len(lives), "channel": channel}
    save_json(STATE_FILE, state, pretty=True)
    total = sum(v.get("uid") == uid for v in store.values())
    ok(f"直播记录 {total} 场 · 本次来源 {len(lives)} 场 · 新增 {fresh} · 修订 {changed}")
    return {"total": total, "source_count": len(lives), "new": fresh, "changed": changed}


def crawl(cfg):
    import requests
    uid, ts = int(cfg["target"]["uid"]), now()
    try:
        # One channel request returns all canonical sessions; no per-viewer or per-session polling.
        with requests.Session() as http:
            http.headers.update({"User-Agent": "HinomeArchive/1.2 (public live statistics)", "Accept": "application/json"})
            r = http.get(API, params={"uid": uid}, timeout=(10, 45))
            r.raise_for_status()
            return ingest(r.json(), uid, ts)
    except Exception:
        state = load_json(STATE_FILE, {})
        if state.get("uid") != uid:
            state = {"schema_version": 3, "uid": uid}
        state.update(last_attempt=ts, last_result={"status": "failed", "ts": ts,
                     "error": "直播来源访问或数据校验失败；已保留旧归档，下次 update 重试"})
        save_json(STATE_FILE, state, pretty=True)
        raise


def payload(uid):
    store = load_json(SESSIONS_FILE, {})
    state = load_json(STATE_FILE, {})
    if state.get("uid") != uid:
        state = {}
    records = []
    for entry in store.values():
        if entry.get("uid") == uid:
            rec = normalize(entry["item"], uid)
            rec.update(first_seen=entry["first_seen"], last_seen=entry["last_seen"],
                       source_missing=bool(state.get("last_success") and entry["last_seen"] < state["last_success"]))
            records.append(rec)
    records.sort(key=lambda r: r["start"], reverse=True)
    return {"sessions": records, "source": SOURCE + str(uid), "last_success": state.get("last_success"),
            "status": (state.get("last_result") or {}).get("status", "unavailable"),
            "source_count": state.get("source_count"), "room_id": (state.get("channel") or {}).get("roomId")}
