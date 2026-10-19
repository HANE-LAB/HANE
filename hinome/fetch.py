"""Stage 1 · FETCH —— 从 B 站抓取空间动态（全量 / 增量），原始数据原样落盘。

两条抓取路线，auto 模式下自动互为备份：
  library : bilibili-api-python 库（上游已停止维护；保留已验证版本）
  raw     : 本文件自带的 requests 实现（WBI 签名 + dm 参数 + buvid），库装不上/坏了时兜底
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from functools import reduce

from .util import (RAW_FILE, STATE_FILE, HISTORY_FILE, load_json, save_json, append_jsonl,
                   jitter_sleep, log, ok, warn, err, now)

FEATURES = ("itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,forwardListHidden,"
            "decorationCard,commentsNewVersion,onlyfansAssetsV2,ugcDelete,onlyfansQaCard")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

HINTS = {
    -352: "触发风控校验。可在本机 config.local.toml 填 sessdata（不要发送到聊天），或稍后再试。",
    -412: "请求被拦截（太频繁）。等 10~30 分钟再跑，或把 page_sleep 调大。",
    -799: "请求过于频繁，稍后再试。",
    -509: "请求过于频繁，稍后再试。",
    -404: "接口不存在，需要检查接口变化；存档与断点会保留。",
    4101131: "该用户空间动态不可见或不存在。",
}


# Rate limits: retrying or switching clients would only add requests; stop and resume on the next run.
THROTTLED = (-412, -799, -509)


class BiliError(Exception):
    def __init__(self, code, msg=""):
        self.code = code
        self.msg = msg
        hint = HINTS.get(code, "")
        super().__init__(f"B站返回 {code} {msg}" + (f"\n    → {hint}" if hint else ""))


# ── 路线一：bilibili-api-python ───────────────────────────────
class LibraryClient:
    name = "library"

    def __init__(self, uid: int, sessdata: str = "", buvid3: str = ""):
        from bilibili_api import user, Credential, sync  # noqa: 若未安装会抛 ImportError
        self._sync = sync
        cred = Credential(sessdata=sessdata or None, buvid3=buvid3 or None)
        self._user = user.User(int(uid), credential=cred)

    def _call(self, coro):
        try:
            return self._sync(coro)
        except Exception as e:  # ResponseCodeException 带 .code/.msg
            if getattr(e, "status", None) == 412:
                raise BiliError(-412, "HTTP 412") from None
            code = getattr(e, "code", None)
            if isinstance(code, int):
                raise BiliError(code, getattr(e, "msg", "")) from None
            raise

    def page(self, offset: str) -> dict:
        return self._call(self._user.get_dynamics_new(offset))

    def followers(self):
        d = self._call(self._user.get_relation_info())
        return (d or {}).get("follower")


# ── 路线二：自带 requests 实现 ────────────────────────────────
MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42,
             19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51,
             30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def wbi_sign(params: dict, mixin_key: str, ts: int | None = None) -> dict:
    p = dict(params)
    p.pop("w_rid", None)
    p["wts"] = int(ts if ts is not None else time.time())
    p = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in sorted(p.items())}
    query = urllib.parse.urlencode(p, quote_via=urllib.parse.quote)
    p["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return p


def mixin_key_from(img_url: str, sub_url: str) -> str:
    stem = lambda u: u.rsplit("/", 1)[-1].split(".")[0]
    orig = stem(img_url) + stem(sub_url)
    return reduce(lambda s, i: s + (orig[i] if i < len(orig) else ""), MIXIN_TAB, "")[:32]


class RawClient:
    name = "raw"

    def __init__(self, uid: int, sessdata: str = "", buvid3: str = ""):
        import requests
        self.uid = int(uid)
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": f"https://space.bilibili.com/{self.uid}/dynamic",
            "Origin": "https://space.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
        })
        b3, b4 = buvid3, ""
        if not b3:
            try:
                spi = self._get("https://api.bilibili.com/x/frontend/finger/spi")
                b3, b4 = spi.get("b_3", ""), spi.get("b_4", "")
            except Exception as e:  # 拿不到也继续
                warn(f"获取 buvid 失败（{e}），继续尝试")
        for k, v in (("buvid3", b3), ("buvid4", b4), ("SESSDATA", sessdata)):
            if v:
                self.s.cookies.set(k, v, domain=".bilibili.com")
        nav = self._get("https://api.bilibili.com/x/web-interface/nav", allow_codes=(0, -101))
        wbi = nav.get("wbi_img") or {}
        self.mixin = mixin_key_from(wbi.get("img_url", ""), wbi.get("sub_url", ""))

    def _get(self, url, params=None, allow_codes=(0,)):
        r = self.s.get(url, params=params, timeout=20)
        if r.status_code == 412:
            raise BiliError(-412, "HTTP 412")
        r.raise_for_status()
        j = r.json()
        code = j.get("code", 0)
        if code not in allow_codes:
            raise BiliError(code, j.get("message", ""))
        return j.get("data") or {}

    def page(self, offset: str) -> dict:
        params = {
            "offset": offset or "",
            "host_mid": self.uid,
            "timezone_offset": -480,
            "platform": "web",
            "features": FEATURES,
            "web_location": "333.1387",
            "x-bili-device-req-json": json.dumps({"platform": "web", "device": "pc"}, separators=(",", ":")),
            "x-bili-web-req-json": json.dumps({"spm_id": "333.1387"}, separators=(",", ":")),
            "dm_img_list": "[]",
            "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
            "dm_cover_img_str": "QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgNjMwIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ",
            "dm_img_inter": '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
        }
        return self._get("https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                         params=wbi_sign(params, self.mixin))

    def followers(self):
        d = self._get("https://api.bilibili.com/x/relation/stat", params={"vmid": self.uid})
        return d.get("follower")


def make_client(kind: str, uid: int, sessdata: str, buvid3: str):
    kind = (kind or "auto").lower()
    order = {"library": [LibraryClient], "raw": [RawClient]}.get(kind, [LibraryClient, RawClient])
    last = None
    for cls in order:
        try:
            c = cls(uid, sessdata, buvid3)
            return c, [k for k in order if k is not cls]
        except ImportError:
            last = "未安装 bilibili-api-python"
            warn("未安装 bilibili-api-python，改用自带请求器（pip install bilibili-api-python 可装上）")
        except Exception as e:
            last = e
            warn(f"{cls.name} 初始化失败：{e}")
    raise RuntimeError(f"所有抓取方式都失败了：{last}")


# ── 主流程 ───────────────────────────────────────────────────
def verify_login(cfg):
    """验证配置中的登录态，不把 Cookie 或响应正文写入日志。"""
    import requests
    try:
        response = requests.get("https://api.bilibili.com/x/web-interface/nav",
                                cookies={"SESSDATA": cfg["bilibili"]["sessdata"]},
                                headers={"User-Agent": UA}, timeout=20, allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        valid = body.get("code") == 0 and (body.get("data") or {}).get("isLogin") is True
    except Exception:
        raise RuntimeError("无法验证 B 站登录态，保留归档；检查网络后重试") from None
    if not valid:
        raise RuntimeError("B 站登录态已失效，请更新本机 config.local.toml 后重试")


def _pub_ts(item: dict) -> int:
    try:
        return int(item["modules"]["module_author"]["pub_ts"])
    except Exception:
        return 0


def _is_pinned(item: dict) -> bool:
    tag = (item.get("modules") or {}).get("module_tag") or {}
    return tag.get("text") == "置顶"


def validate_page(data, offset):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or data.get("has_more") not in (True, False, 0, 1):
        raise ValueError("动态接口响应缺少合法的 items/has_more，不能判断历史结束")
    items = data["items"]
    if any(not isinstance(it, dict) or not str(it.get("id_str", "")).isdigit() or _pub_ts(it) <= 0 for it in items):
        raise ValueError("动态接口包含无效记录，保留断点")
    if not items:
        raise ValueError("动态接口返回空页，无法区分风控/访客限制与真实末尾；保留断点，不标记完成")
    if data["has_more"] and (not data.get("offset") or str(data["offset"]) == offset):
        raise ValueError("分页游标未前进，保留断点")
    return data


def read_page(client, spares, cfg, offset):
    """A terminal page needs two matching responses, because Bilibili can return transient empty pages."""
    terminal = None
    attempt = 0
    while True:
        try:
            data = validate_page(client.page(offset), offset)
            if any(int(it["modules"]["module_author"].get("mid", 0)) != int(cfg["target"]["uid"]) for it in data["items"]):
                raise ValueError("接口返回了其他作者的动态，拒绝混入归档")
            if data["has_more"]:
                return data, client
            signature = tuple(str(it["id_str"]) for it in data["items"])
            if terminal == signature:
                return data, client
            terminal = signature
            raise ValueError("接口报告历史末尾，等待第二次相同结果确认")
        except Exception as e:
            if isinstance(e, BiliError) and e.code in THROTTLED:
                raise
            attempt += 1
            if attempt >= 4:
                if not spares:
                    raise
                cls = spares.pop(0)
                bc = cfg["bilibili"]
                warn(f"{client.name} 连续失败，切换 {cls.name}；断点不变")
                client = cls(int(cfg["target"]["uid"]), bc.get("sessdata", ""), bc.get("buvid3", ""))
                attempt, terminal = 0, None
            wait = 8 * max(1, attempt)
            warn(f"{str(e).splitlines()[0]}；{wait} 秒后重试")
            time.sleep(wait)


def crawl(cfg: dict, full: bool = False, max_pages: int | None = None) -> dict:
    """Checkpoint every page. Only a confirmed end completes a historical traversal."""
    from .archive import observe, snapshot
    from .merge import merge_raw
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages 必须大于 0")
    bc = cfg["bilibili"]
    access = "authenticated" if bc.get("sessdata") else "guest"
    if access == "authenticated":
        verify_login(cfg)
    uid = int(cfg["target"]["uid"])
    store: dict = load_json(RAW_FILE, {})
    state: dict = load_json(STATE_FILE, {})
    if state.get("schema_version", 0) < 4:
        state["history_complete"] = False
        state.pop("last_success", None)
        state.pop("last_complete_full", None)
    if state.get("uid", uid) != uid:
        raise ValueError("data/ 属于其他 UID，请使用独立目录，不能混合归档")
    if state.get("access") != access:
        # 不同可见范围的分页与缺失次数不能接在一起。
        state.pop("checkpoint", None)
        state.pop("last_complete_full", None)
        state["history_complete"] = False
        for rec in store.values():
            for key in ("missing_since", "missing_full_runs", "last_missing_scan"):
                rec.pop(key, None)
    t_run = now()
    checkpoint = state.get("checkpoint") if not full else None
    full = bool(full or checkpoint or not state.get("history_complete") or
                t_run - state.get("last_complete_full", 0) >= int(bc.get("full_refresh_days", 7)) * 86400)
    if full:
        checkpoint = checkpoint or {"started_at": t_run, "offset": "", "seen": [], "visited": [], "pages": 0}
        state["checkpoint"] = checkpoint
    state.update(uid=uid, schema_version=4, access=access, last_attempt=t_run,
                 last_result={"status": "running", "ts": t_run})
    save_json(STATE_FILE, state, pretty=True)
    for rec in store.values():
        snapshot(rec["item"], rec.get("last_seen") or rec.get("first_seen") or t_run)
    mode = "全量" if full else "增量"
    log(f"目标 UID {uid} · {mode}抓取 · 已存 {len(store)} 条")

    known = set(store)
    cutoff = now() - int(bc.get("refresh_days", 30)) * 86400
    offset = checkpoint["offset"] if full else ""
    seen = set(checkpoint["seen"]) if full else set()
    visited = set(checkpoint["visited"]) if full else set()
    pages = new_count = gone = 0
    complete = throttled = False
    client = None

    def remember(it):
        iid, ts = str(it["id_str"]), now()
        incoming = {"item": it, "first_seen": ts, "last_seen": ts,
                    "content_access": access, "content_seen": ts}
        rec = merge_raw({iid: store[iid]} if iid in store else {}, {iid: incoming})[iid]
        for key in ("gone", "missing_since", "missing_full_runs", "last_missing_scan"):
            rec.pop(key, None)
        store[iid] = rec
        observe(rec["item"], ts)
        seen.add(iid)

    try:
        client, spares = make_client(bc.get("fetcher", "auto"), uid, bc.get("sessdata", ""), bc.get("buvid3", ""))
        log(f"抓取方式：{client.name}" + (f" · 从已保存的第 {checkpoint['pages']} 页继续" if full and offset else ""))
        if full and offset:
            # A long historical backfill must not prevent saving today's new posts.
            head, client = read_page(client, spares, cfg, "")
            for it in head["items"]:
                iid = str(it["id_str"])
                if iid not in store:
                    new_count += 1
                remember(it)
            checkpoint["seen"] = sorted(seen)
            save_json(RAW_FILE, store)
            save_json(STATE_FILE, state, pretty=True)
            log("已刷新最新一页，继续补历史")
        while True:
            if offset in visited:
                raise ValueError("检测到分页循环；请用 --full 从头复核，已有数据不会删除")
            data, client = read_page(client, spares, cfg, offset)
            items = data["items"]
            if items and all(str(it["id_str"]) in seen for it in items):
                raise ValueError("分页只返回已见记录，不能继续或判定完成")
            pages += 1
            stop = False
            for it in items:
                iid = str(it["id_str"])
                if iid not in store:
                    new_count += 1
                remember(it)
                if not full and iid in known and not _is_pinned(it) and _pub_ts(it) < cutoff:
                    stop = True
            save_json(RAW_FILE, store)
            oldest = min((_pub_ts(i) for i in items), default=0)
            log(f"第 {pages:>3} 页 · {len(items):>2} 条 · 最早到 {time.strftime('%Y-%m-%d', time.localtime(oldest)) if oldest else '-'} · 库内 {len(store)} 条（已保存）")
            if stop or not data["has_more"]:
                complete = True
                break
            visited.add(offset)
            offset = str(data["offset"])
            if full:
                checkpoint.update(offset=offset, seen=sorted(seen), visited=sorted(visited), pages=checkpoint["pages"] + 1)
                save_json(STATE_FILE, state, pretty=True)
            if max_pages and pages >= max_pages:
                warn("达到本次页数上限；历史尚未完成，下次 update 会继续")
                break
            jitter_sleep(bc.get("page_sleep", [1.5, 3.5]))
        if full and complete:
            # A visitor or risk-controlled list can end early with has_more=false; posts older than anything
            # this traversal reached were not checked, so they are not counted as missing. A list holding only
            # pinned posts reached no point in the timeline at all, so it counts nothing.
            reached = min((_pub_ts(store[i]["item"]) for i in seen if i in store and not _is_pinned(store[i]["item"])), default=None)
            for iid, rec in store.items():
                if access == "authenticated" and reached is not None and iid not in seen and rec.get("last_missing_scan") != checkpoint["started_at"] \
                        and _pub_ts(rec.get("item") or {}) >= reached:
                    rec.setdefault("missing_since", t_run)
                    rec["missing_full_runs"] = rec.get("missing_full_runs", 0) + 1
                    rec["last_missing_scan"] = checkpoint["started_at"]
                    if rec["missing_full_runs"] >= 2 and not rec.get("gone"):
                        rec["gone"] = now()
                        gone += 1
            state.update(history_complete=True, last_complete_full=now(), last_full_crawl=now())
            state.pop("checkpoint", None)
            save_json(RAW_FILE, store)
        if complete:
            state["last_success"] = now()
        state.update(last_crawl=now(), fetcher=client.name,
                     last_result={"status": "ok" if complete else "partial", "ts": now(), "pages": pages, "total": len(store)})
    except BaseException as e:
        state["last_result"] = {"status": "failed", "ts": now(), "error": str(e).splitlines()[0][:200] if str(e) else "已中断"}
        throttled = isinstance(e, BiliError) and e.code in THROTTLED
        raise
    finally:
        save_json(STATE_FILE, state, pretty=True)
        followers = None
        if client and not throttled:
            try:
                followers = client.followers()
            except Exception as e:
                warn(f"粉丝数获取失败：{str(e).splitlines()[0]}")
        append_jsonl(HISTORY_FILE, {"ts": now(), "followers": followers, "posts": len(store), "fetch_status": state["last_result"]["status"]})
    (ok if complete else warn)(f"{'抓取完成' if complete else '抓取未完成，已保存断点'}：{pages} 页，新增 {new_count} 条，库内 {len(store)} 条")
    return {"mode": mode, "pages": pages, "new": new_count, "total": len(store), "complete": complete,
            "gone": gone, "followers": followers, "fetcher": client.name}
