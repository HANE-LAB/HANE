"""改完页面模板后的视觉检查：用无头浏览器给示例页面截图，并报告报错、横向溢出和帧率。

    pip install playwright && python -m playwright install chromium   # 只需一次
    python dev/shots.py              # 先跑 dev/demo.py，再截图到 dev/.sandbox/shots/
    python dev/shots.py --no-build   # 直接用已有的 dev/.sandbox/demo/site/index.html

截图清单：桌面动态环（1.5 秒、7 秒）、拖动后的 Kobuta、点开一条动态的抽屉、统计/全文/数据链三页（整页）、
手机竖屏动态环、轻点 Kobuta 和统计页、减少动态效果模式，以及 3 条 / 0 条 / 2000 条三种数据量的动态环。
无头浏览器是软件渲染，帧率会比真机低很多，只用来对比改动前后。
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "dev" / ".sandbox" / "demo"
OUT = REPO / "dev" / ".sandbox" / "shots"
FPS_JS = """() => new Promise(res => { let n = 0, t0 = performance.now();
  function f(t) { n++; if (t - t0 < 2500) requestAnimationFrame(f); else res(n / ((t - t0) / 1000)); } requestAnimationFrame(f); })"""
OVERFLOW_JS = "document.documentElement.scrollWidth - innerWidth"
PIG_JS = """() => { const el = document.getElementById('kobuta-pet'); if (!el || el.closest('[hidden]')) return null;
  const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2,
  inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight}; }"""


def variants() -> dict[str, Path]:
    """用示例数据派生出 3 条 / 0 条 / 2000 条三种极端情况的页面。"""
    tpl = (DEMO / "hinome" / "template.html").read_text(encoding="utf-8")
    data = json.loads((DEMO / "site" / "data.json").read_text(encoding="utf-8"))
    tpl = re.sub(r"<!--DEV-->.*?<!--/DEV-->", "", tpl, flags=re.S)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DEMO / "site" / "assets", OUT / "assets", dirs_exist_ok=True)
    out = {}

    def emit(name, d):
        p = OUT / f"_{name}.html"
        p.write_text(tpl.replace("/*__DATA__*/null", json.dumps(d, ensure_ascii=False).replace("<", "\\u003c")), encoding="utf-8")
        out[name] = p

    d = copy.deepcopy(data); d["posts"] = sorted(d["posts"], key=lambda p: p["ts"])[:3]; emit("tiny", d)
    d = copy.deepcopy(data); d["posts"] = []; emit("zero", d)
    random.seed(7)
    d = copy.deepcopy(data); base, posts = d["posts"], []
    t0, t1 = 1665500000, 1791000000
    for i in range(2000):
        p = copy.deepcopy(random.choice(base)); p["id"] = f"big{i}"; p["pinned"] = False
        p["ts"] = t0 + int((t1 - t0) * (i + random.random()) / 2000)
        u = (p["ts"] - t0) / (t1 - t0)
        like = int(random.lognormvariate(4 + 3 * u, 0.7)); com = int(like * random.uniform(0.05, 0.2)); fw = int(like * random.uniform(0.01, 0.06))
        p["stats"] = {"like": like, "comment": com, "forward": fw}; p["score"] = like + 3 * com + 5 * fw
        if random.random() < 0.5:
            p["type"] = "live"
        posts.append(p)
    d["posts"] = posts; emit("big", d)
    return out


async def shoot() -> int:
    from playwright.async_api import async_playwright
    page_url = (DEMO / "site" / "index.html").as_uri()
    problems = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()

        async def new(ctx_kw=None, **kw):
            ctx = await b.new_context(**(ctx_kw or {}), **kw)
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: problems.append(f"页面报错：{e}"))
            pg.on("console", lambda m: m.type == "error" and "ERR_" not in m.text and problems.append(f"控制台错误：{m.text}"))
            return pg

        pg = await new(viewport={"width": 1440, "height": 900})
        await pg.goto(page_url)
        await pg.wait_for_timeout(1500); await pg.screenshot(path=OUT / "desk_ring_1.png")
        await pg.wait_for_timeout(5500); await pg.screenshot(path=OUT / "desk_ring_2.png")
        print(f"桌面 动态环  帧率≈{await pg.evaluate(FPS_JS):.0f}  横向溢出 {await pg.evaluate(OVERFLOW_JS)}px")
        # Kobuta: always shown, draggable anywhere, keeps running after it lands.
        pet = await pg.evaluate(PIG_JS)
        if not pet or not pet["inside"]:
            problems.append(f"桌面：Kobuta 不可见或超出屏幕 {pet}")
        else:
            await pg.mouse.move(pet["x"], pet["y"]); await pg.mouse.down()
            for k in range(1, 13):
                await pg.mouse.move(pet["x"] + (360 - pet["x"]) * k / 12, pet["y"] + (640 - pet["y"]) * k / 12); await pg.wait_for_timeout(16)
            await pg.wait_for_timeout(200); await pg.mouse.up(); await pg.wait_for_timeout(500)
            moved = await pg.evaluate(PIG_JS)
            await pg.wait_for_timeout(400); await pg.screenshot(path=OUT / "desk_kobuta.png")
            later = await pg.evaluate(PIG_JS)
            if not await pg.evaluate("localStorage.getItem('hane-kobuta-spot')") or abs(moved["x"] - 360) > 260 or abs(moved["y"] - 640) > 120:
                problems.append(f"桌面：拖动 Kobuta 后没有落在放下的位置 {moved}")
            if (later["x"], later["y"]) == (moved["x"], moved["y"]) or not later["inside"]:
                problems.append("桌面：Kobuta 落地后没有继续跑")
            await pg.evaluate("localStorage.removeItem('hane-kobuta-spot')")
        hit = None
        for y in range(240, 860, 6):                    # 找一束光点开抽屉
            await pg.mouse.move(980, y)
            if await pg.evaluate("getComputedStyle(document.getElementById('c-fx')).cursor") == "pointer":
                hit = y; break
        if hit:
            await pg.mouse.click(980, hit); await pg.wait_for_timeout(400)
            await pg.screenshot(path=OUT / "desk_drawer.png"); await pg.keyboard.press("Escape")
        else:
            problems.append("桌面：没找到可以点的光束")
        for v in ("stats", "archive", "pipeline"):
            if v == "pipeline":
                await pg.goto((DEMO / "site-dev" / "index.html").as_uri())
            await pg.click(f'.tab[data-v="{v}"]'); await pg.wait_for_timeout(500)
            await pg.screenshot(path=OUT / f"desk_{v}.png", full_page=True)
            ov = await pg.evaluate(OVERFLOW_JS)
            print(f"桌面 {v:<9} 横向溢出 {ov}px")
            if ov > 0:
                problems.append(f"桌面 {v} 横向溢出 {ov}px")

        ph = await new(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        await ph.goto(page_url); await ph.wait_for_timeout(5000)
        await ph.screenshot(path=OUT / "phone_ring.png")
        pet = await ph.evaluate(PIG_JS)
        if not pet or not pet["inside"]:
            problems.append(f"手机：Kobuta 不可见或超出屏幕 {pet}")
        else:
            await ph.touchscreen.tap(pet["x"], pet["y"]); await ph.wait_for_timeout(250)
            await ph.screenshot(path=OUT / "phone_kobuta.png")
            if not await ph.evaluate("document.getElementById('kobuta-pet').hasAttribute('data-say')"):
                problems.append("手机：轻点 Kobuta 没有反应")
        # iPhone 上从信笺开始的手指一旦变成页面滚动，WebKit 发 pointercancel，pointerleave 只发给手指下的子元素。
        await ph.evaluate("""() => { const t = document.getElementById('now-txt'), o = {pointerId: 9, pointerType: 'touch', isPrimary: true};
          for (const type of ['pointerdown', 'pointercancel']) t.dispatchEvent(new PointerEvent(type, {...o, bubbles: true}));
          t.dispatchEvent(new PointerEvent('pointerleave', o)); }""")
        await ph.wait_for_timeout(700)
        before = await ph.locator("#scrub-cur").get_attribute("style")
        await ph.wait_for_timeout(500)
        if await ph.locator("#scrub-cur").get_attribute("style") == before:
            problems.append("手机：触摸滚动（pointercancel）之后动态环停住不动")
        await ph.click('.tab[data-v="stats"]'); await ph.wait_for_timeout(500)
        await ph.screenshot(path=OUT / "phone_stats.png", full_page=True)
        ov = await ph.evaluate(OVERFLOW_JS)
        print(f"手机 统计页  横向溢出 {ov}px")
        if ov > 0:
            problems.append(f"手机统计页横向溢出 {ov}px")

        # 在后台打开的页面一开始可能没有宽度；之后有了尺寸，动态环要排好版并继续播放。
        zw = await new(viewport={"width": 1, "height": 900})
        await zw.goto(page_url); await zw.wait_for_timeout(1500)
        await zw.set_viewport_size({"width": 1440, "height": 900}); await zw.wait_for_timeout(1500)
        before = await zw.locator("#scrub-cur").get_attribute("style")
        await zw.wait_for_timeout(600)
        if await zw.locator("#scrub-cur").get_attribute("style") == before:
            problems.append("零宽度加载、恢复尺寸之后动态环停住不动")

        # 录制模式：只剩转盘、铺满窗口，停在网址指定的日期，并提供给录制脚本的接口。
        fm = await new(viewport={"width": 1920, "height": 1080})
        await fm.goto(page_url + "?film&at=2025-03-01&paused"); await fm.wait_for_timeout(1500)
        await fm.screenshot(path=OUT / "film.png")
        box, ledger = await fm.locator("#viz").bounding_box(), await fm.locator("#ledger").inner_text()
        print(f"录制模式  转盘 {box and round(box['height'])}px 高  帳：{ledger.splitlines()[0] if ledger else '—'}")
        if await fm.locator(".hd").is_visible() or not box or box["height"] < 1070 or not ledger.startswith("2025 年 3 月"):
            problems.append("录制模式：界面没有隐藏、转盘没有铺满，或没有跳到网址里的日期")
        if await fm.evaluate("typeof (window.HANE || {}).seek") != "function":
            problems.append("录制模式：没有 window.HANE 接口")

        rm = await new(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        await rm.goto(page_url); await rm.wait_for_timeout(2000); await rm.screenshot(path=OUT / "desk_reduced_motion.png")
        pet = await rm.evaluate(PIG_JS)
        if pet:   # still running, but no particles, hops or squash
            await rm.mouse.click(pet["x"], pet["y"]); await rm.wait_for_timeout(300)
            if await rm.evaluate("document.querySelectorAll('.pig-fx').length"):
                problems.append("减少动态：Kobuta 仍在生成粒子特效")
            await rm.wait_for_timeout(300)
            if await rm.evaluate(PIG_JS) == pet:
                problems.append("减少动态：Kobuta 停止了奔跑")
        # Autoplay is intentional even with reduced motion; controls remain readable.
        play = rm.locator("#btn-play")
        if not await play.is_visible() or await play.get_attribute("aria-pressed") != "true":
            problems.append("默认自动播放未启动或按钮不可见")
        else:
            cursor = rm.locator("#scrub-cur")
            before = await cursor.get_attribute("style")
            await rm.wait_for_timeout(1200)
            if await cursor.get_attribute("style") == before:
                problems.append("默认自动播放：时间轴没有前进")
            await play.click()
            paused = await cursor.get_attribute("style")
            await rm.wait_for_timeout(500)
            if await cursor.get_attribute("style") != paused:
                problems.append("暂停后时间轴仍在前进")
            await rm.locator('#playback-settings > summary').click()
            await rm.locator('#btn-speed').click()
            if await rm.locator('#btn-speed').inner_text() != '速度 2×':
                problems.append("播放设置：速度切换没有生效")
            await rm.locator('#render-quality').select_option('lite')
            if await rm.locator('#render-status').inner_text() != '流畅特效':
                problems.append("播放设置：画质切换没有生效")
            await rm.locator('#render-quality').press('Escape')
            if await rm.locator('#playback-settings').evaluate('(el) => el.open') or not await rm.locator('#playback-settings > summary').evaluate('(el) => el === document.activeElement'):
                problems.append("播放设置：Escape 没有收起并归还焦点")
            await rm.locator('#playback-settings > summary').click()
            month = await rm.locator('#dial-month').inner_text()
            await rm.locator('#dial-next').click()
            await rm.wait_for_timeout(100)
            if await rm.locator('#playback-settings').evaluate('(el) => el.open') or await rm.locator('#dial-month').inner_text() == month:
                problems.append("月份导航：没有切月或没有收起播放设置")
            await play.click()
            if await play.evaluate('(el) => el.getBoundingClientRect().height') < 48:
                problems.append("播放按钮高度不足 48px")

        for name, path in variants().items():
            vp = await new(viewport={"width": 1440, "height": 900})
            await vp.goto(path.as_uri()); await vp.wait_for_timeout(3500)
            await vp.screenshot(path=OUT / f"variant_{name}.png")
            fps = await vp.evaluate(FPS_JS) if name != "zero" else 0
            print(f"数据量 {name:<5} 截图完成" + (f"  帧率≈{fps:.0f}" if fps else ""))
        await b.close()
    print(f"\n截图在：{OUT}")
    for p in problems:
        print("✗ " + p)
    print("没有发现报错。" if not problems else f"共 {len(problems)} 个问题。")
    return 1 if problems else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-build", action="store_true", help="不重新生成示例页面")
    a = ap.parse_args()
    try:
        import playwright  # noqa: F401
    except ImportError:
        sys.exit("需要先安装：pip install playwright && python -m playwright install chromium")
    if not a.no_build or not (DEMO / "site" / "index.html").exists():
        subprocess.run([sys.executable, str(REPO / "dev" / "demo.py")], check=True)
    OUT.mkdir(parents=True, exist_ok=True)
    sys.exit(asyncio.run(shoot()))


if __name__ == "__main__":
    main()
