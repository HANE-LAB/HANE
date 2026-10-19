"""git 合并驱动：本机和 GitHub Actions 都更新过 data/ 时，按内容合并，而不是逐行比较。

    动态存档 raw_items.json   按动态 id 合并，同一条取更新鲜的那份（first_seen 取更早的）
    翻译/大模型缓存            两边的条目取并集
    state.json                时间戳取较大值
    *.jsonl（运行记录、粉丝数） 两边的行取并集，按时间排序、去重

python lab.py publish 和 GitHub Actions 会自动注册这个驱动；手动注册：
    git config merge.hinome-data.driver "python -m hinome.merge %O %A %B %P"
.gitattributes 把 data/ 下的文件指向它。git 调用时：%O 共同祖先，%A 当前版本（结果写回这里），%B 另一边，%P 文件路径。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def merge_raw(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, rb in b.items():
        ra = out.get(k)
        if ra is None:
            out[k] = rb
            continue
        fresh_a = max(ra.get("last_seen") or 0, ra.get("gone") or 0)
        fresh_b = max(rb.get("last_seen") or 0, rb.get("gone") or 0)
        win = dict(rb if fresh_b > fresh_a else ra)
        firsts = [x for x in (ra.get("first_seen"), rb.get("first_seen")) if x]
        if firsts:
            win["first_seen"] = min(firsts)
        out[k] = win
    return out


def merge_deep(a: dict, b: dict) -> dict:
    out = dict(b)
    for k, v in a.items():
        out[k] = merge_deep(v, out[k]) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def merge_state(a: dict, b: dict) -> dict:
    if max(a.get("schema_version", 0), b.get("schema_version", 0)) >= 3:
        # A checkpoint and its completion flag belong to the same traversal.
        stamp = lambda s: max(s.get("last_attempt", 0), (s.get("last_result") or {}).get("ts", 0))
        return dict(b if stamp(b) > stamp(a) else a)
    out = {**b, **a}
    for k in set(a) & set(b):
        x, y = a[k], b[k]
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            out[k] = max(x, y)
    return out


def merge_jsonl(*texts: str) -> str:
    seen, rows = set(), []
    for t in texts:
        for line in t.splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            try:
                ts = json.loads(line).get("ts") or 0
            except (ValueError, AttributeError):
                ts = 0
            rows.append((ts, line))
    rows.sort(key=lambda r: r[0])
    return "".join(line + "\n" for _, line in rows)


def merge_file(ours: Path, theirs: Path, name: str) -> None:
    a_txt, b_txt = ours.read_text(encoding="utf-8"), theirs.read_text(encoding="utf-8")
    if name.endswith(".jsonl"):
        ours.write_text(merge_jsonl(a_txt, b_txt), encoding="utf-8")
        return
    a, b = json.loads(a_txt or "{}"), json.loads(b_txt or "{}")
    if name in ("raw_items.json", "live_sessions.json"):
        merged = merge_raw(a, b)
    elif name in ("state.json", "live_state.json"):
        merged = merge_state(a, b)
    elif name in ("llm_notes.json", "media.json", "translation_review.json"):
        merged = dict(a)
        for key, value in b.items():
            old = merged.get(key, {})
            stamp = "saved_at" if name == "media.json" else "ts"
            if key not in merged or value.get(stamp, 0) > old.get(stamp, 0):
                merged[key] = value
    elif "item" in a and "ts" in a and "item" in b:
        merged = a if a["ts"] <= b["ts"] else b
    else:
        merged = merge_deep(a, b)
    pretty = name == "state.json"   # 和 util.save_json 的格式保持一致
    ours.write_text(json.dumps(merged, ensure_ascii=False, indent=1 if pretty else None,
                               separators=None if pretty else (",", ":")), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print("用法：python -m hinome.merge %O %A %B %P", file=sys.stderr)
        return 2
    _base, ours, theirs, path = argv[1:5]
    try:
        merge_file(Path(ours), Path(theirs), Path(path).name)
        return 0
    except Exception as e:   # 合并不了就交还给 git，按冲突处理
        print(f"hinome.merge：{path} 自动合并失败：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
