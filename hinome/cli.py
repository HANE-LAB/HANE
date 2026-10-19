"""命令行入口：python lab.py <命令>

  update   整条链：抓取 → 规整 → 翻译 → 分析 → 生成页面（日常就用这个）
  process  不联网抓取，只用已存数据重新 规整 → 翻译 → 分析 → 生成页面
  fetch    只抓取
  live     更新直播场次与历史版本，用缓存重建页面
  publish  先同步 GitHub 上的数据 → update → 把 data/ 提交并推送（网站放在 GitHub Pages 时用）
  doctor   体检：Python 版本、依赖、B 站连通、各翻译后端是否可用
  open     用浏览器打开生成的页面
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
import time
import traceback
import webbrowser

from . import __version__
from .util import (load_config, load_json, save_json, append_jsonl, stage, log, ok, warn, err,
                   RAW_FILE, POSTS_FILE, LLM_CACHE_FILE, RUNLOG_FILE, STATE_FILE, SITE, ROOT, now, data_lock)


class Run:
    """记录每个阶段的结果，最后写进 runs.jsonl，页面上的 PIPELINE 面板就是读它。"""

    def __init__(self):
        self.stages = []

    def add(self, name, status, count=None, detail="", t0=None):
        self.stages.append({"name": name, "status": status, "count": count, "detail": detail,
                            "secs": round(time.time() - t0, 1) if t0 else None})


def do_process(cfg, run: Run, backend=None, demo=False):
    from .normalize import normalize
    from .translate import translate_posts
    from .analyze import analyze_posts
    from .build import build_site

    stage("NORMALIZE", "整理原始数据")
    t0 = time.time()
    state = load_json(STATE_FILE, {})
    if (state.get("last_result") or {}).get("status") == "running":
        state["last_result"] = {"status": "failed", "ts": now(), "error": "上次抓取意外中断；已保存断点，下次 update 继续"}
        save_json(STATE_FILE, state, pretty=True)
    store = load_json(RAW_FILE, {})
    if not store:
        err("还没有任何数据，先运行：python lab.py update")
        run.add("normalize", "fail", 0, "无数据", t0)
        return None
    posts, icons = normalize(store)
    bad = sum(1 for p in posts if p.get("parse_error"))
    ok(f"{len(posts)} 条动态" + (f"，{bad} 条解析异常" if bad else ""))
    run.add("normalize", "ok" if not bad else "warn", len(posts), f"{bad} 条解析异常" if bad else "", t0)

    stage("TRANSLATE", "翻译成中文")
    t0 = time.time()
    llm_cache = load_json(LLM_CACHE_FILE, {})
    use_llm_analysis = cfg["analysis"].get("llm", "auto") != "off"
    try:
        st = translate_posts(posts, cfg, backend, llm_cache)
        translated = sum(1 for p in posts if p.get("zh") or p.get("title_zh"))
        status = "ok" if not st.get("failed") and (st.get("backend") or not st.get("need")) else "warn"
        detail = f"后端 {st.get('backend') or '无'} · 需翻 {st.get('need', 0)} 条" + (f" · 失败 {st['failed']}" if st.get("failed") else "")
        run.add("translate", status, translated, detail, t0)
    except Exception as e:
        err(f"翻译阶段出错：{e}")
        traceback.print_exc()
        run.add("translate", "fail", 0, str(e)[:120], t0)

    stage("ANALYZE", "标签 · 关键词 · 译文自检")
    t0 = time.time()
    st = analyze_posts(posts, llm_cache if use_llm_analysis else {})
    run.add("analyze", "ok", len(posts), f"大模型标注 {st['llm_tagged']} · 待复核 {st['qa_flagged']}", t0)
    save_json(POSTS_FILE, posts)

    stage("BUILD", "生成页面")
    t0 = time.time()
    out = build_site(posts, icons, cfg, run.stages + [{"name": "build", "status": "ok", "count": len(posts)}], demo=demo)
    run.add("build", "ok", len(posts), out.name, t0)
    return out


def do_live(cfg, run):
    from .live import crawl
    stage("LIVE", "从 nailv 的 Danmakus 来源归档实际直播场次")
    t0 = time.time()
    try:
        result = crawl(cfg)
        run.add("live", "ok", result["total"], f"来源 {result['source_count']} 场 · 新增 {result['new']} · 修订 {result['changed']}", t0)
        return True
    except Exception as e:
        warn(f"直播抓取失败，保留旧归档：{e}")
        run.add("live", "warn", None, "来源访问/校验失败，保留旧归档，下次重试", t0)
        return False


def cmd_live(args, cfg):
    run = Run()
    success = do_live(cfg, run)
    out = do_process(cfg, run, backend="none")
    append_jsonl(RUNLOG_FILE, {"ts": now(), "stages": run.stages})
    _finish(out, cfg, args)
    return (_stage_code(run) if success else 2) if out else 1


def cmd_update(args, cfg):
    from .fetch import crawl
    run = Run()
    live_ok = do_live(cfg, run) if cfg.get("live", {}).get("enabled", True) else True
    stage("FETCH", "从 B 站抓取动态")
    t0 = time.time()
    code = 0
    try:
        st = crawl(cfg, full=args.full, max_pages=args.max_pages)
        code = 0 if st["complete"] else 2
        run.add("fetch", "ok" if st["complete"] else "warn", st["total"],
                f"{st['mode']} · {st['pages']} 页 · 新增 {st['new']} · 方式 {st['fetcher']}"
                + (" · 未完成，已保存断点" if not st["complete"] else "")
                + (f" · 粉丝 {st['followers']}" if st.get("followers") is not None else ""), t0)
    except Exception as e:
        code = 1
        err(f"抓取失败：{e}")
        if args.verbose:
            traceback.print_exc()
        run.add("fetch", "fail", None, str(e).split("\n")[0][:160], t0)
        if not load_json(RAW_FILE, {}):
            append_jsonl(RUNLOG_FILE, {"ts": now(), "stages": run.stages})
            return 1
        warn("用已有数据继续生成页面")
    if cfg.get("archive", {}).get("download_images", True):
        from .archive import archive_images
        stage("MEDIA", "保存动态图片（失败项下次继续）")
        t0 = time.time()
        try:
            media = archive_images()
            run.add("media", "warn" if media["failed"] else "ok", media["saved"],
                    f"发现 {media['total']} · 新存 {media['new']} · 失败 {media['failed']}", t0)
            if media["failed"]:
                code = code or 2
        except Exception as e:
            run.add("media", "fail", None, str(e)[:160], t0)
            code = 1
    out = do_process(cfg, run, args.backend)
    if not live_ok:
        code = code or 2
    append_jsonl(RUNLOG_FILE, {"ts": now(), "stages": run.stages})
    _finish(out, cfg, args)
    return (code or _stage_code(run)) if out else 1


def cmd_process(args, cfg):
    run = Run()
    out = do_process(cfg, run, args.backend)
    append_jsonl(RUNLOG_FILE, {"ts": now(), "stages": run.stages})
    _finish(out, cfg, args)
    return _stage_code(run) if out else 1


def _stage_code(run):
    return 1 if any(s["status"] == "fail" for s in run.stages) else (2 if any(s["status"] == "warn" for s in run.stages) else 0)


def cmd_setup_translation(args, cfg):
    from .local_mt import setup
    setup()
    return 0


def cmd_fetch(args, cfg):
    from .fetch import crawl
    stage("FETCH")
    result = crawl(cfg, full=args.full, max_pages=args.max_pages)
    return 0 if result["complete"] else 2


def cmd_media(args, cfg):
    from .archive import archive_images
    result = archive_images()
    log(str(result))
    return 0 if not result["failed"] else 2


def _finish(out, cfg, args):
    if not out:
        return
    print()
    ok(f"完成。打开这个文件查看：{out}")
    if cfg["output"].get("open_browser", True) and not args.no_open:
        try:
            webbrowser.open(out.resolve().as_uri())
        except Exception:
            pass


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def _tail(text: str) -> str:
    lines = [x for x in (text or "").strip().splitlines() if x.strip()]
    return lines[-1] if lines else "（没有输出）"


def cmd_publish(args, cfg):
    """本地更新并推到 GitHub。GitHub Actions 收到推送后会重建并发布网页（见 docs/DEPLOY.md）。"""
    stage("PUBLISH", "同步 GitHub 上的最新数据")
    try:
        if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
            err("这个文件夹还不是 git 仓库。先按 docs/DEPLOY.md 把它放到 GitHub 上。")
            return 1
    except FileNotFoundError:
        err("没找到 git 命令。先安装 Git：https://git-scm.com/downloads")
        return 1
    # 注册按内容合并数据的驱动（.gitattributes 里指定了 data/ 用它），两边都更新过数据也能自动合并
    _git("config", "merge.hinome-data.name", "hinome data merge")
    _git("config", "merge.hinome-data.driver", f'"{Path(sys.executable).as_posix()}" -m hinome.merge %O %A %B %P')
    if _git("status", "--porcelain", "--", "data").stdout.strip():
        _git("add", "data")
        commit = _git("commit", "-m", "data: local changes")
        if commit.returncode:
            err("保存本地数据提交失败：" + _tail(commit.stderr or commit.stdout))
            return 1
    before = _git("rev-parse", "HEAD").stdout.strip()
    r = _git("pull", "--rebase")
    if r.returncode != 0:
        _git("rebase", "--abort")
        err("拉取 GitHub 上的数据失败：" + _tail(r.stderr))
        log("如果是冲突：本地和远端改动需要合并。本地数据没丢，")
        log("先保留本地归档，再按 docs/DEPLOY.md 的恢复说明处理。")
        return 1
    ok("已和 GitHub 同步")
    # This process already loaded the old cli/util/config; running the update now would mix old and new modules.
    changed = _git("diff", "--name-only", before, "HEAD", "--", "hinome", "lab.py", "config.toml",
                   "requirements.txt", "constraints.txt").stdout.split() if before else []
    if changed:
        warn("GitHub 上的程序也更新了，已同步到本机。为免新旧代码混用，这次没有抓取；请再运行一次 publish。")
        if {"requirements.txt", "constraints.txt"} & set(changed):
            log("依赖清单也有变化：先运行 python -m pip install -r requirements.txt（用本项目 .venv 里的 python）。")
        return 2
    args.no_open = True
    code = cmd_update(args, cfg)
    stage("PUBLISH", "提交数据并推送")
    _git("add", "data")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        ok("数据没有变化，不需要推送")
        return code
    c = _git("commit", "-m", time.strftime("data: local update %Y-%m-%d %H:%M"))
    if c.returncode != 0:
        err("提交失败：" + _tail(c.stderr or c.stdout))
        return 1
    p = _git("push")
    if p.returncode != 0:
        err("推送失败：" + _tail(p.stderr))
        log("检查网络、GitHub 登录和远端变更；本地提交已保留，可恢复后重试 git push。")
        return 1
    ok("已推送。GitHub Actions 会在几分钟内重新发布网页。")
    return code


def cmd_open(args, cfg):
    folder = SITE if cfg["output"].get("edition", "release") == "release" else SITE.parent / "site-dev"
    p = folder / "index.html"
    if not p.exists():
        err("还没生成页面，先运行：python lab.py update")
        return 1
    webbrowser.open(p.resolve().as_uri())
    return 0


def cmd_doctor(args, cfg):
    import importlib
    import platform
    stage("DOCTOR", "环境体检")
    v = sys.version_info
    (ok if v >= (3, 10) else err)(f"Python {platform.python_version()}" + ("" if v >= (3, 10) else " —— 需要 3.10 或更高"))
    for mod, why in [("requests", "必需"), ("bilibili_api", "抓取首选"), ("curl_cffi", "抓取库的网络层（可选）"),
                     ("httpx", "抓取库的网络层（可选）"), ("aiohttp", "抓取库的网络层（可选）"),
                     ("jieba", "中文关键词"), ("janome", "日文关键词")]:
        try:
            importlib.import_module(mod)
            ok(f"{mod:<14} 已安装  · {why}")
        except ImportError:
            warn(f"{mod:<14} 未安装  · {why}")

    stage("B 站连通")
    from .fetch import make_client, read_page, BiliError
    healthy = True
    try:
        c, spares = make_client(cfg["bilibili"].get("fetcher", "auto"), cfg["target"]["uid"],
                           cfg["bilibili"].get("sessdata", ""), cfg["bilibili"].get("buvid3", ""))
        d, c = read_page(c, spares, cfg, "")
        items = d.get("items") or []
        name = ((items[0].get("modules") or {}).get("module_author") or {}).get("name") if items else "?"
        ok(f"{c.name}：拿到第一页 {len(items)} 条（作者：{name}）")
        try:
            ok(f"粉丝数：{c.followers()}")
        except Exception as e:
            warn(f"粉丝数获取失败：{e}")
    except BiliError as e:
        healthy = False
        err(str(e))
    except Exception as e:
        healthy = False
        err(f"连接失败：{e}")
    if not cfg["bilibili"].get("sessdata"):
        log("提示：没填 sessdata。能抓就不用管；遇到 -352 再按 README 填上。")

    stage("翻译后端")
    from .translate import BACKENDS
    usable = set()
    for n in ("hymt", "google", "ollama", "deepl", "claude"):
        b = BACKENDS[n](cfg["translate"])
        try:
            good, info = b.available()
            if good and not b.is_llm:
                sample = b.translate_batch(["今日も配信来てくれてありがとう！"])[0]
                info = f"试翻：{sample}"
            (ok if good else warn)(f"{n:<10} {'可用' if good else '不可用'}  {info}")
            if good:
                usable.add(n)
        except Exception as e:
            warn(f"{n:<10} 出错：{e}")
        finally:
            b.close()
    print()
    selected = cfg["translate"].get("backend", "auto")
    from .translate import AUTO_ORDER
    translation_ok = selected == "none" or (bool(usable.intersection(AUTO_ORDER)) if selected == "auto" else selected in usable)
    return 0 if healthy and translation_ok else 1


def main(argv=None):
    # Windows pipes can default to GBK, which cannot encode our status symbols.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    p = argparse.ArgumentParser(prog="lab.py", description="HANE · B站动态抓取/翻译/分析/可视化")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    def common(sp, fetch=False):
        sp.add_argument("--edition", choices=("release", "dev"), help="正式展示版或本地开发版")
        sp.add_argument("--backend", help="临时指定翻译后端：hymt/google/ollama/deepl/claude/none")
        sp.add_argument("--no-open", action="store_true", help="跑完不自动打开浏览器")
        sp.add_argument("-v", "--verbose", action="store_true")
        if fetch:
            sp.add_argument("--full", action="store_true", help="全量复核（登录态下核对不可见动态）")
            sp.add_argument("--guest", action="store_true", help="强制游客采集，不使用本机或环境中的登录态")
            sp.add_argument("--max-pages", type=int, default=None, help="最多抓几页（调试用）")

    common(sub.add_parser("update", help="整条链更新（日常用这个）"), fetch=True)
    common(sub.add_parser("process", help="不抓取，只重新翻译/分析/生成页面"))
    common(sub.add_parser("publish", help="同步 GitHub → update → 推送数据（网站放在 GitHub Pages 时用）"), fetch=True)
    sp = sub.add_parser("fetch", help="只抓取")
    sp.add_argument("--full", action="store_true")
    sp.add_argument("--guest", action="store_true")
    sp.add_argument("--max-pages", type=int, default=None)
    sub.add_parser("doctor", help="环境体检")
    sp = sub.add_parser("open", help="打开页面")
    sp.add_argument("--edition", choices=("release", "dev"))
    sub.add_parser("media", help="补存所有已归档动态的图片")
    sp = sub.add_parser("live", help="只更新直播场次，并用缓存重建页面")
    sp.add_argument("--edition", choices=("release", "dev"))
    sp.add_argument("--no-open", action="store_true")
    sub.add_parser("setup-translation", help="下载免费免注册的 HY-MT 离线翻译模型（约 1.13 GB）")

    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["update"] + (argv or sys.argv[1:]))
    cfg = load_config()
    if getattr(args, "guest", False):
        cfg["bilibili"].update(sessdata="", buvid3="")
    if getattr(args, "edition", None):
        cfg["output"]["edition"] = args.edition
    print(f"HANE v{__version__} · {cfg['target']['name']} · UID {cfg['target']['uid']}")
    if cfg.get("_secrets_in_shared") and (ROOT / ".git").exists():
        warn("config.toml 里填了 " + "、".join(cfg["_secrets_in_shared"]) + "，而这个文件会被 git 提交。"
             "请把它们挪到 config.local.toml（不会被提交），再清空 config.toml 里的值。")
    try:
        command = {"update": cmd_update, "process": cmd_process, "fetch": cmd_fetch, "publish": cmd_publish,
                   "doctor": cmd_doctor, "open": cmd_open, "media": cmd_media, "live": cmd_live,
                   "setup-translation": cmd_setup_translation}[args.cmd]
        if args.cmd in ("update", "process", "fetch", "publish", "media", "live"):
            with data_lock():
                return command(args, cfg)
        return command(args, cfg)
    except KeyboardInterrupt:
        print()
        warn("已中断。已抓到/翻译的部分都存下来了，下次接着跑。")
        return 130
    except Exception as e:
        err(str(e))
        return 1
