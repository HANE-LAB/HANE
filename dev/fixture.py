"""生成虚构的示例数据（形状和 B 站 web-dynamic 接口返回的一致），用来离线测试整条流程、渲染样式预览。
不是任何真人的动态。一般不直接运行它，用 dev/demo.py。

    python dev/fixture.py <项目根目录> <输出的 data 目录>
"""
import json, random, sys, time
from pathlib import Path

sys.path.insert(0, sys.argv[1])  # project root
from hinome.translate import needs_translation

out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
random.seed(7)
JST = 9 * 3600

PAIRS = [  # (kind, ja, zh)
 ("pre", "今夜21時から雑談配信します！\nお便りもたくさん読むので来てね[打call]", "今晚21点开始杂谈直播！\n会读很多来信，快来哦[打call]"),
 ("pre", "明日の夜はホラーゲームやります…こわい[哭泣]", "明天晚上玩恐怖游戏……好可怕[哭泣]"),
 ("pre", "今日は歌枠！リクエストも受け付けるよ〜", "今天是歌回！也接受点歌哦～"),
 ("pre", "22時からマイクラ配信、拠点づくりの続きします", "22点开始MC直播，继续建基地"),
 ("pre", "今週の配信スケジュールです！\n月：雑談\n水：ゲーム\n土：歌枠", "这是本周的直播日程！\n周一：杂谈\n周三：游戏\n周六：歌回"),
 ("thx", "昨日の配信ありがとう！みんなのコメント全部読んだよ[脱单doge]", "谢谢昨天来看直播！大家的评论我全都看了[脱单doge]"),
 ("thx", "フォロワー1万人突破しました！本当にありがとう！", "粉丝突破1万了！真的非常感谢！"),
 ("thx", "提督になってくれた方、本当にありがとうございます。大事にします", "成为提督的各位，真的非常感谢。我会好好珍惜的"),
 ("thx", "千舰達成…！夢みたい。みんなと一緒に来られてよかった[大哭]", "千舰达成……！像做梦一样。能和大家一起走到这里真好[大哭]"),
 ("day", "お昼はラーメン食べた🍜 しょうゆ派です", "午饭吃了拉面🍜 我是酱油派"),
 ("day", "寝坊しました…ごめんなさい[捂脸]", "睡过头了……对不起[捂脸]"),
 ("day", "中国語の勉強、ちょっとずつ頑張ってます！\n「你好」はもう言えるよ", "中文学习在一点点努力中！\n「你好」已经会说了哦"),
 ("day", "今日はゆっくり休みます。みんなも無理しないでね", "今天好好休息。大家也别太勉强自己哦"),
 ("day", "新しい衣装、もうすぐお披露目です…お楽しみに！", "新衣装马上就要公开了……敬请期待！"),
 ("day", "雨の日はなんだか眠くなるね", "下雨天总觉得会犯困呢"),
 ("song", "新しい歌ってみた動画を投稿しました！聴いてくれると嬉しいです", "投稿了新的翻唱视频！希望大家能听听"),
 ("song", "オリジナル曲のMV、ついに公開！", "原创曲的MV终于公开了！"),
 ("goods", "誕生日グッズの予約が始まりました！アクスタとボイスがあるよ", "生日周边开始预约了！有亚克力立牌和语音哦"),
 ("bday", "誕生日配信ありがとう！最高の一日でした[大哭]", "谢谢来看生日直播！是最棒的一天[大哭]"),
 ("bday", "活動1周年記念配信、今夜20時から！", "活动1周年纪念直播，今晚20点开始！"),
 ("collab", "@DemoFriendA さんとコラボします！今夜22時から", "要和 @DemoFriendA 联动了！今晚22点开始"),
 ("collab", "@DemoFriendB ちゃんと一緒にゲームしたよ、楽しかった！", "和 @DemoFriendB 一起玩游戏了，好开心！"),
 ("collab", "@DemoFriendA @DemoFriendC と三人でお泊まり雑談しました", "和 @DemoFriendA @DemoFriendC 三个人进行了过夜杂谈"),
 ("game", "ポケモン新作、ついにクリアしました！", "宝可梦新作终于通关了！"),
 ("game", "APEXでチャンピオン取れた！やったー！", "APEX吃鸡了！太好了！"),
 ("event", "#虚拟主播# 企画に参加します！投票よろしくね", "#虚拟主播# 要参加企划了！请多多投票哦"),
 ("zh", "大家好！今天也辛苦了[星星眼]", None),
 ("zh", "谢谢大家的礼物！明天见～", None),
]
VID = [("【歌ってみた】Demo Cover", "【翻唱】Demo 翻唱曲"), ("【初配信】はじめまして！Demoです", "【初次直播】初次见面！我是 Demo"),
       ("【切り抜き】寝坊した日の話", "【切片】睡过头那天的故事"), ("【オリジナル曲】Demo Song MV", "【原创曲】Demo Song MV")]
LIVE = [("【雑談】ゆるっと夜ふかし","【杂谈】悠闲熬夜"), ("【ホラー】こわいゲームやる","【恐怖】玩可怕的游戏"), ("【歌枠】リクエスト歌枠","【歌回】点歌歌回"), ("【マイクラ】拠点づくり","【MC】建造基地")]
EMO = {"[打call]": "https://i0.hdslb.com/bfs/emote/431432c43da3ee5aab5b0e4f8931953e649e9975.png"}
MENT = {"DemoFriendA": "1001", "DemoFriendB": "1002", "DemoFriendC": "1003"}

seg_cache = {}
def seed(ja, zh):
    for la, lb in zip(ja.split("\n"), zh.split("\n")):
        if la.strip() and needs_translation(la):
            seg_cache[la] = lb

def rich(text):
    nodes = []
    import re
    pos = 0
    for m in re.finditer(r"\[[^\]]+\]|@\S+|#[^#]+#", text):
        if m.start() > pos: nodes.append({"type": "RICH_TEXT_NODE_TYPE_TEXT", "text": text[pos:m.start()], "orig_text": text[pos:m.start()]})
        t = m.group(0)
        if t.startswith("["):
            nodes.append({"type": "RICH_TEXT_NODE_TYPE_EMOJI", "text": t, "orig_text": t, "emoji": {"text": t, "icon_url": EMO.get(t, "")}})
        elif t.startswith("@"):
            nodes.append({"type": "RICH_TEXT_NODE_TYPE_AT", "text": t, "orig_text": t, "rid": MENT.get(t[1:], "")})
        else:
            nodes.append({"type": "RICH_TEXT_NODE_TYPE_TOPIC", "text": t, "orig_text": t, "jump_url": "//search.bilibili.com/all?keyword=" + t.strip("#")})
        pos = m.end()
    if pos < len(text): nodes.append({"type": "RICH_TEXT_NODE_TYPE_TEXT", "text": text[pos:], "orig_text": text[pos:]})
    return {"text": text, "rich_text_nodes": nodes}

def author(ts, action=""):
    return {"name": "示例主播 Demo", "mid": 0, "face": "", "pub_ts": ts, "pub_action": action, "pub_time": ""}

def stat(base):
    return {"like": {"count": base}, "comment": {"count": max(1, base // random.randint(6, 14))}, "forward": {"count": base // random.randint(25, 60)}}

def pic(seed):
    return {"url": f"https://i0.hdslb.com/bfs/new_dyn/demo{seed}.jpg", "width": 1200, "height": 900}

items = {}
start = int(time.mktime((2024, 9, 1, 0, 0, 0, 0, 0, 0)))
end = int(time.mktime((2026, 10, 12, 0, 0, 0, 0, 0, 0)))
n = 230
ts_list = sorted(random.randint(start, end) for _ in range(n))
for i, t in enumerate(ts_list):
    # snap to plausible JST hours
    day = (t + JST) // 86400 * 86400 - JST
    hour = random.choices([12, 13, 18, 19, 20, 21, 22, 23, 0, 1], [4, 3, 6, 8, 10, 12, 12, 9, 5, 2])[0]
    t = day + hour * 3600 + random.randint(0, 3599)
    prog = (t - start) / (end - start)
    base = int(80 + 900 * prog ** 1.6 + random.randint(0, 120))
    iid = str(900000000000000000 + i * 7919)
    r = random.random()
    mods = {"module_author": author(t), "module_dynamic": {}, "module_stat": stat(base)}
    item = {"id_str": iid, "visible": True, "basic": {}, "modules": mods}
    if r < 0.14:
        title_ja, title_zh = random.choice(VID)
        seed(title_ja, title_zh)
        item["type"] = "DYNAMIC_TYPE_AV"; mods["module_author"]["pub_action"] = "投稿了视频"
        mods["module_dynamic"] = {"desc": rich("新しい動画です！見てね"), "major": {"type": "MAJOR_TYPE_ARCHIVE", "archive": {
            "title": title_ja, "desc": "", "cover": f"//i0.hdslb.com/bfs/archive/demo{i}.jpg", "bvid": f"BV1Demo{i:05d}x",
            "duration_text": f"{random.randint(1,12)}:{random.randint(10,59)}", "stat": {"play": f"{base*12/10000:.1f}万" if base*12>10000 else str(base*12), "danmaku": str(base//3)},
            "jump_url": f"//www.bilibili.com/video/BV1Demo{i:05d}x/"}}}
        seed("新しい動画です！見てね", "新视频来了！快去看")
    elif r < 0.30:
        title, tzh = random.choice(LIVE); seed(title, tzh)
        item["type"] = "DYNAMIC_TYPE_LIVE_RCMD"; mods["module_author"]["pub_action"] = "直播了"
        mods["module_dynamic"] = {"desc": None, "major": {"type": "MAJOR_TYPE_LIVE_RCMD", "live_rcmd": {"content": json.dumps({"live_play_info": {
            "title": title, "cover": f"https://i0.hdslb.com/bfs/live/demo{i}.jpg", "area_name": random.choice(["虚拟日常", "虚拟Singer", "单机游戏"]),
            "live_start_time": t, "link": "//live.bilibili.com/0000", "watched_show": {"text_large": f"{base*3}人看过"}}}, ensure_ascii=False)}}}
    elif r < 0.40:
        item["type"] = "DYNAMIC_TYPE_FORWARD"
        kind, ja, zh = random.choice(PAIRS[:-2])
        seed("拡散お願いします！", "求扩散！")
        mods["module_dynamic"] = {"desc": rich("拡散お願いします！"), "major": None}
        o_ja, o_zh = random.choice([("新グッズ発売のお知らせです。", "新周边发售通知。"), ("コラボ配信の告知です！", "联动直播预告！")])
        seed(o_ja, o_zh)
        item["orig"] = {"id_str": str(800000000000000000 + i), "type": "DYNAMIC_TYPE_DRAW", "modules": {
            "module_author": {"name": random.choice(list(MENT)), "mid": 1001, "pub_ts": t - 3600},
            "module_dynamic": {"desc": None, "major": {"type": "MAJOR_TYPE_OPUS", "opus": {"summary": rich(o_ja), "pics": [pic(f"o{i}")]}}}}}
    else:
        kind, ja, zh = random.choice(PAIRS)
        if zh: seed(ja, zh)
        has_pic = random.random() < 0.45
        item["type"] = "DYNAMIC_TYPE_DRAW" if has_pic else "DYNAMIC_TYPE_WORD"
        mods["module_dynamic"] = {"desc": None, "major": {"type": "MAJOR_TYPE_OPUS", "opus": {
            "title": None, "summary": rich(ja), "pics": [pic(f"{i}_{k}") for k in range(random.randint(1, 4))] if has_pic else [],
            "jump_url": f"//www.bilibili.com/opus/{iid}"}}}
        if kind == "pre" and random.random() < 0.5:
            mods["module_dynamic"]["additional"] = {"type": "ADDITIONAL_TYPE_RESERVE", "reserve": {"title": "直播预约：今晚的直播", "desc1": {"text": "今天 21:00 直播"}, "desc2": {"text": f"{base//2}人预约"}}}
        if kind in ("thx", "bday") and "1万" in ja or "千舰" in ja:
            mods["module_stat"] = stat(base * 4)
    items[iid] = {"item": item, "first_seen": t + 600, "last_seen": end}

# one pinned, one locked
last = items[str(900000000000000000 + (n - 1) * 7919)]
last["item"]["modules"]["module_tag"] = {"text": "置顶"}
lk = items[str(900000000000000000 + (n - 5) * 7919)]["item"]
lk["type"] = "DYNAMIC_TYPE_DRAW"; lk.pop("orig", None)
lk["modules"]["module_dynamic"] = {"desc": None, "major": {"type": "MAJOR_TYPE_BLOCKED", "blocked": {"hint_message": "充电专属动态"}}}
items[str(900000000000000000 + 40 * 7919)]["gone"] = end

json.dump(items, open(out / "raw_items.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"echo": seg_cache}, open(out / "translations.json", "w", encoding="utf-8"), ensure_ascii=False)
with open(out / "history.jsonl", "w", encoding="utf-8") as f:
    for k in range(0, 60):
        tt = start + (end - start) * k // 59
        f.write(json.dumps({"ts": tt, "followers": int(1200 + 38000 * (k / 59) ** 1.7 + random.randint(-150, 150)), "posts": int(n * k / 59)}) + "\n")
print("items", len(items), "segments", len(seg_cache))

# Fictional livestreams, separate from the dynamic-card fixtures; include a missing year and midnight crossing.
from hinome import live
from datetime import datetime, timezone
from uuid import UUID
sessions = []
for i in range(24):
    dt = datetime(2023 if i < 3 else 2026, 9 if i < 12 else 10, i % 12 + 1, 14, 30, tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    sessions.append({"liveId": str(UUID(int=i + 1)), "title": "虚构直播 · 示例歌回 " + str(i + 1),
                     "startDate": ms, "stopDate": ms + (3600000 if i else 9000000), "isFinish": True,
                     "isFull": i % 7 != 0, "totalIncome": i * 123.45, "danmakusCount": i * 300,
                     "watchCount": i * 700, "payCount": i * 3, "interactionCount": i * 10, "maxOnlineCount": 0})
live.ingest({"code": 200, "data": {"channel": {"uId": 0, "roomId": 8, "totalLiveCount": len(sessions)}, "lives": sessions}}, 0, max(end, max(s["stopDate"] for s in sessions) // 1000 + 3600))
