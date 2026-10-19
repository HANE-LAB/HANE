"""Stage 5 · BUILD —— 把数据塞进页面模板，生成可离线打开的单文件网页。"""
from __future__ import annotations

import base64
import json
import re
import shutil
import zlib
from pathlib import Path

from . import __version__
from .util import (SITE, HISTORY_FILE, RUNLOG_FILE, STATE_FILE, MEDIA_FILE, MEDIA,
                   read_jsonl, load_json, save_json, ok, now)

TEMPLATE = Path(__file__).resolve().parent / "template.html"

KEEP = ("id", "ts", "url", "type", "action", "pinned", "locked", "gone", "text", "title", "images", "cover",
        "video", "live", "article", "reserve", "vote", "related", "orig", "stats", "mentions", "hashtags",
        "emotes", "links", "lang", "zh", "title_zh", "orig_zh", "tr", "tags", "tags_src", "tags_rule", "mood",
        "summary", "kw_zh", "kw_ja", "qa", "score", "first_seen", "reviewed_fields", "review_stale")


def build_site(posts: list, icons: dict, cfg: dict, stages: list, demo: bool = False) -> Path:
    from .archive import histories
    from .translate import _fields
    from .live import payload as live_payload
    edition = cfg.get("output", {}).get("edition", "release")
    if edition not in ("release", "dev"):
        raise ValueError("output.edition 必须为 release 或 dev")
    dest_site = SITE if edition == "release" else SITE.parent / "site-dev"
    required = [(r, _fields(r, bool(cfg["translate"].get("translate_forward_origin", True)))) for r in posts]
    assets = TEMPLATE.parent / "assets"
    if assets.is_dir():
        # site/assets is generated: rebuild it so renamed or retired files (old sprite sheets) do not linger.
        shutil.rmtree(dest_site / "assets", ignore_errors=True)
        shutil.copytree(assets, dest_site / "assets", dirs_exist_ok=True)
    state = load_json(STATE_FILE, {})
    manifest = load_json(MEDIA_FILE, {})
    local_images = {}
    for url, entry in manifest.items():
        name = entry.get("file", "")
        if name and Path(name).name == name and (MEDIA / name).is_file():
            (dest_site / "media").mkdir(parents=True, exist_ok=True)
            dest = dest_site / "media" / name
            if not dest.exists() or dest.stat().st_size != (MEDIA / name).stat().st_size:
                shutil.copy2(MEDIA / name, dest)
            local_images[url] = "media/" + name
    slim = [{k: r[k] for k in KEEP if r.get(k) not in (None, "", [], {}, False)} for r in posts]
    payload = {
        "meta": {
            "uid": cfg["target"]["uid"],
            "name": cfg["target"]["name"],
            "generated_at": now(),
            "demo": demo,
            "edition": edition,
            "version": __version__,
            "translation_needed": sum(bool(fields) for _, fields in required),
            "translation_done": sum(bool(fields) and all(r.get(k, "").strip() for k, _ in fields) for r, fields in required),
            "history_complete": bool(state.get("schema_version", 0) >= 4 and state.get("history_complete")),
            "last_fetch": state.get("last_result", {}),
            "last_success": state.get("last_success"),
            "checkpoint_pages": (state.get("checkpoint") or {}).get("pages", 0),
            "images_saved": len(local_images),
            "images_failed": sum(bool(v.get("error")) for v in manifest.values()),
        },
        "posts": slim,
        "live": live_payload(int(cfg["target"]["uid"])),
        "emote_icons": icons,
        "history": sorted(read_jsonl(HISTORY_FILE), key=lambda r: r.get("ts") or 0),
        "post_history": {} if demo else histories(),
        "local_images": local_images,
        "runs": (sorted(read_jsonl(RUNLOG_FILE), key=lambda r: r.get("ts") or 0) + ([{"ts": now(), "stages": stages}] if stages else []))[-30:] if edition == "dev" else [],
    }
    if edition == "release":
        payload.pop("runs")
        for key in ("last_fetch", "last_success", "checkpoint_pages", "images_failed"):
            payload["meta"].pop(key, None)
    # Inside <script>, "</script" ends the block and "<!--<script" changes how the parser finds the end; escape every "<".
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8")
    if edition == "release":
        html = re.sub(r"<!--DEV-->.*?<!--/DEV-->", "", html, flags=re.S)
        # No readable JSON in the published page: deflate + base64, unpacked by the template's unpack() (DecompressionStream).
        js = 'await unpack("' + base64.b64encode(zlib.compress(js.encode("utf-8"), 9)).decode("ascii") + '")'
    html = html.replace("/*__DATA__*/null", js, 1)
    dest_site.mkdir(parents=True, exist_ok=True)
    out = dest_site / "index.html"
    tmp = out.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out)
    save_json(dest_site / "data.json", payload)
    ok(f"页面已生成：{out}  （{len(html) // 1024} KB）")
    return out
