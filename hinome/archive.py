"""Immutable raw versions, observation history and resumable public-image downloads."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .normalize import parse_item
from .util import (SNAPSHOTS, METRICS, MEDIA, MEDIA_FILE, RAW_FILE, load_json,
                   save_json, append_jsonl, read_jsonl, now, log, warn)


def snapshot(item: dict, ts: int) -> str:
    iid = str(item.get("id_str", ""))
    if not iid.isdigit():
        raise ValueError("动态 ID 无效，不能写入存档")
    digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = SNAPSHOTS / iid / f"{digest}.json"
    if not path.exists():
        save_json(path, {"ts": ts, "item": item})
    return digest


def observe(item: dict, ts: int):
    digest = snapshot(item, ts)
    rec = parse_item(item)
    month = time.strftime("%Y-%m", time.gmtime(ts))
    append_jsonl(METRICS / f"{month}.jsonl", {
        "ts": ts, "id": rec["id"], "stats": rec["stats"], "snapshot": digest,
        "video": rec.get("video", {}), "live": rec.get("live", {}),
    })


def histories() -> dict:
    result = {}
    for path in sorted(METRICS.glob("*.jsonl")):
        for row in read_jsonl(path):
            result.setdefault(row["id"], {"observations": [], "revisions": []})["observations"].append(row)
    for folder in SNAPSHOTS.iterdir() if SNAPSHOTS.exists() else []:
        if not folder.is_dir():
            continue
        versions = []
        by_hash = {}
        for path in folder.glob("*.json"):
            row = load_json(path, {})
            r = parse_item(row["item"])
            version = {"ts": row["ts"], **{k: r.get(k) for k in ("text", "title", "images", "cover", "orig")}}
            versions.append(version)
            by_hash[path.stem] = version
        for observation in result.get(folder.name, {}).get("observations", []):
            version = by_hash.get(observation.get("snapshot"))
            if version:
                versions.append({**version, "ts": observation["ts"]})
        previous = None
        for row in sorted(versions, key=lambda r: r["ts"]):
            fingerprint = json.dumps({k: v for k, v in row.items() if k != "ts"}, sort_keys=True)
            if fingerprint != previous:
                result.setdefault(folder.name, {"observations": [], "revisions": []})["revisions"].append(row)
                previous = fingerprint
    for history in result.values():
        history["observations"].sort(key=lambda row: row["ts"])
    return result


def image_urls(item: dict) -> set[str]:
    rec = parse_item(item)
    urls = set(rec.get("images") or [])
    if rec.get("cover"):
        urls.add(rec["cover"])
    orig = rec.get("orig") or {}
    urls.update(orig.get("images") or [])
    if orig.get("cover"):
        urls.add(orig["cover"])
    return urls


def safe_image_url(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return (p.scheme == "https" and not p.username and not p.password and p.port in (None, 443)
            and any(host == d or host.endswith("." + d) for d in ("hdslb.com", "biliimg.com")))


def download_image(session, url: str) -> str:
    current = "https://" + url[7:] if url.startswith("http://") else url
    for _ in range(5):
        if not safe_image_url(current):
            raise ValueError("图片地址不是允许的 B 站 HTTPS CDN，已跳过")
        response = session.get(current, stream=True, timeout=30, allow_redirects=False)
        if response.is_redirect:
            from urllib.parse import urljoin
            current = urljoin(current, response.headers.get("Location", ""))
            response.close()
            continue
        break
    else:
        raise ValueError("图片重定向次数过多")
    with response:
        response.raise_for_status()
        types = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif"}
        ext = types.get(response.headers.get("Content-Type", "").split(";")[0].lower())
        if not ext:
            raise ValueError("CDN 没有返回支持的图片类型")
        name = hashlib.sha256(url.encode()).hexdigest() + ext
        MEDIA.mkdir(parents=True, exist_ok=True)
        path = MEDIA / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            total = 0
            with open(tmp, "wb") as f:
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 50 * 1024 * 1024:
                        raise ValueError("单张图片超过 50 MiB，已记录待人工保存")
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            if not total:
                raise ValueError("CDN 返回了空文件")
            from PIL import Image
            with Image.open(tmp) as img:
                img.verify()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    return name


def archive_images() -> dict:
    import requests
    urls = set()
    for wrap in load_json(RAW_FILE, {}).values():
        urls.update(image_urls(wrap["item"]))
    for path in SNAPSHOTS.glob("*/*.json"):
        urls.update(image_urls(load_json(path, {})["item"]))
    manifest = load_json(MEDIA_FILE, {})
    done = failed = 0
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0"
        for url in sorted(urls):
            entry = manifest.get(url, {})
            if entry.get("file") and Path(entry["file"]).name == entry["file"] and (MEDIA / entry["file"]).is_file():
                continue
            try:
                name = download_image(session, url)
                manifest[url] = {"file": name, "bytes": (MEDIA / name).stat().st_size, "saved_at": now()}
                done += 1
            except Exception as e:
                manifest[url] = {"error": str(e).splitlines()[0][:200], "attempted_at": now()}
                failed += 1
                warn(f"图片保存失败：{str(e).splitlines()[0]}")
            save_json(MEDIA_FILE, manifest)
            if (done + failed) % 20 == 0:
                log(f"图片：本轮已保存 {done}，失败 {failed}")
            time.sleep(1)
    return {"total": len(urls), "saved": sum(bool(manifest.get(u, {}).get("file")) for u in urls), "new": done, "failed": failed}
