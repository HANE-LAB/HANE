"""用虚构示例数据在沙盒里跑一遍整条流程，生成样式预览。不会碰项目里的 data/ 和 site/。

    python dev/demo.py            # 生成 dev/.sandbox/demo/site/index.html
    python dev/demo.py --open     # 生成后用浏览器打开

同时会生成 dev/.sandbox/demo/preview.html：页面模板里 <!--CONTENT--> 标记之间的部分，
用来发布成 claude.ai 的 Artifact 预览（不含 doctype，发布时会自动套上外壳）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SANDBOX = REPO / "dev" / ".sandbox" / "demo"


def build() -> Path:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True)
    shutil.copytree(REPO / "hinome", SANDBOX / "hinome", ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("lab.py", "config.toml"):          # 故意不复制 config.local.toml：示例数据不需要任何密钥
        shutil.copy2(REPO / f, SANDBOX / f)
    py = sys.executable
    subprocess.run([py, "-X", "utf8", str(REPO / "dev" / "fixture.py"), str(SANDBOX), str(SANDBOX / "data")], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([py, "-X", "utf8", str(Path(__file__).resolve()), "--inner", str(SANDBOX)], check=True)
    page = SANDBOX / "site" / "index.html"
    html = page.read_text(encoding="utf-8")
    a, b = html.index("<!--CONTENT-->") + len("<!--CONTENT-->"), html.index("<!--/CONTENT-->")
    (SANDBOX / "preview.html").write_text(html[a:b].strip() + "\n", encoding="utf-8")
    return page


def inner(root: str) -> None:
    """在沙盒副本里运行（这样 hinome.util 里的路径都指向沙盒）。"""
    sys.path.insert(0, root)
    import random
    from hinome import cli
    from hinome.util import load_config, RUNLOG_FILE

    random.seed(3)
    RUNLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNLOG_FILE, "w", encoding="utf-8") as f:   # 虚构的运行记录，让 PIPELINE 面板有内容可看
        t = int(time.mktime((2026, 8, 20, 21, 0, 0, 0, 0, 0)))
        for i in range(18):
            t += 86400 * 3
            f.write(json.dumps({"ts": t, "stages": [
                {"name": "fetch", "status": "warn" if i == 5 else "ok", "count": 200 + i * 2,
                 "detail": "-352 风控，已切换 raw 重试成功" if i == 5 else "增量 · 2 页 · 新增 2 · library"},
                {"name": "normalize", "status": "ok", "count": 200 + i * 2},
                {"name": "translate", "status": "warn" if i == 11 else "ok", "count": 190 + i * 2,
                 "detail": "后端 echo" + (" · 失败 3" if i == 11 else "")},
                {"name": "analyze", "status": "ok", "count": 200 + i * 2},
                {"name": "build", "status": "ok", "count": 200 + i * 2}]}, ensure_ascii=False) + "\n")
    cfg = load_config()
    cfg["output"]["edition"] = "release"
    cfg["target"]["name"] = "示例主播 Demo"
    cfg["target"]["uid"] = 0
    cfg["analysis"]["llm"] = "off"
    run = cli.Run()
    run.add("fetch", "ok", 230, "增量 · 3 页 · 新增 2 · library · 粉丝 3.9万")
    if not cli.do_process(cfg, run, backend="echo", demo=True):
        sys.exit(1)
    cfg["output"]["edition"] = "dev"
    if not cli.do_process(cfg, cli.Run(), backend="echo", demo=True):
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    ap.add_argument("--inner", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.inner:
        inner(a.inner)
        return
    page = build()
    print(f"\n示例页面：{page}\nArtifact 预览片段：{SANDBOX / 'preview.html'}")
    if a.open:
        webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
