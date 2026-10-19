"""离线单元测试（不联网）：翻译标记往返、各翻译后端的请求/响应处理（模拟 HTTP）、WBI 签名、语言判断、各类动态的解析。

    python dev/test_units.py
"""
import json, sys, re
from pathlib import Path
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent))
from hinome import translate as T
from hinome import fetch as F
from hinome.normalize import parse_item, _new_acc

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))
    fails += 0 if cond else 1

# markup round trip
line = "@火羽ひのめ さんとコラボ！[打call] #虚拟主播# https://b23.tv/x <3 & more"
mk = T.to_markup(line, ('<span class="notranslate">', "</span>"))
check("markup wraps mention", '<span class="notranslate">@火羽ひのめ</span>' in mk, mk)
check("markup escapes <&", "&lt;3 &amp; more" in mk, mk)
check("markup roundtrip", T.from_markup(mk) == line, T.from_markup(mk))

class Resp:
    def __init__(self, data, status=200, text=""):
        self._d, self.status_code, self.text = data, status, text
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)

class FakeHTTP:
    def __init__(self): self.calls = []; self.headers = {}
    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if "translate.googleapis.com" in url: return Resp([[["你好，", "こんにちは、", None], ["谢谢", "ありがとう", None]], None, "ja"])
        if url.endswith("/api/tags"): return Resp({"models": [{"name": "qwen2.5:7b"}]})
        raise RuntimeError(url)
    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if "deepl.com" in url:
            return Resp({"translations": [{"text": "和<x>@火羽ひのめ</x>联动！"} for _ in kw["json"]["text"]]})
        if url.endswith("/api/chat"):
            return Resp({"message": {"content": '```json\n{"zh":"今晚直播！","tags":["直播预告","不存在"],"mood":"开心","summary":"预告"}\n```'}})
        if "anthropic.com" in url:
            return Resp({"content": [{"type": "text", "text": '{"zh":"谢谢","tags":["感谢/里程碑"],"mood":"感动","summary":"致谢"}'}]})
        raise RuntimeError(url)

cfg = {"ollama": {"host": "http://localhost:11434", "model": "qwen2.5:7b"}, "deepl": {"api_key": "k:fx"}, "claude": {"api_key": "sk", "model": "claude-haiku-5-5"}}
check("retired backends are not executable", "argos" not in T.BACKENDS and "microsoft" not in T.BACKENDS)

g = T.Google(cfg); g.http = FakeHTTP()
check("google joins sentences", g.translate_batch(["こんにちは、ありがとう"]) == ["你好，谢谢"])
d = T.DeepL(cfg); d.http = FakeHTTP()
check("deepl free endpoint + xml", d.translate_batch(["@火羽ひのめ さんとコラボ！"]) == ["和@火羽ひのめ联动！"] and "api-free" in d.http.calls[-1][1] and d.http.calls[-1][2]["json"]["tag_handling"] == "xml")
o = T.Ollama(cfg); o.http = FakeHTTP()
check("ollama available w/ model", o.available()[0])
note = o.chat_json(T.llm_prompt("今夜配信します"))
check("ollama json parse + tag filter", note["zh"] == "今晚直播！" and note["tags"] == ["直播预告"] and note["mood"] == "开心", note)
c = T.Claude(cfg); c.http = FakeHTTP()
note = c.chat_json("x")
check("claude parse", note["zh"] == "谢谢" and note["tags"] == ["感谢/里程碑"], note)
hdr = c.http.calls[-1][2]["headers"]
check("claude headers", hdr["x-api-key"] == "sk" and hdr["anthropic-version"] == "2023-06-01")

# lang detection
for txt, want in [("今夜21時から配信！", "ja"), ("配信開始", "ja"), ("大家好！今天也辛苦了", "zh"), ("[doge][doge]", "none"), ("Thank you everyone", "en"), ("谢谢大家[打call]", "zh")]:
    check(f"lang {txt!r}", T.detect_lang(txt) == want, T.detect_lang(txt))

# assemble line vs segment caches
cache = {"今夜21時から配信！": "今晚21点开始直播！", "ありがとう": "谢谢"}
check("assemble multi-line", T.assemble("今夜21時から配信！\n[doge]ありがとう", cache) == "今晚21点开始直播！\n[doge]谢谢", T.assemble("今夜21時から配信！\n[doge]ありがとう", cache))

# WBI signing against the algorithm documented by bilibili-API-collect
mk_ = F.mixin_key_from("https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                       "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png")
check("mixin key", mk_ == "ea1db124af3c7062474693fa704f4ff8", mk_)
signed = F.wbi_sign({"foo": "114", "bar": "514", "zab": 1919810}, mk_, ts=1702204169)
check("wbi w_rid", signed["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4", signed)

# library-compatible item with opus + forward + live_rcmd
item = {"id_str": "1", "type": "DYNAMIC_TYPE_FORWARD", "modules": {
    "module_author": {"pub_ts": "1700000000", "name": "A", "mid": 1},
    "module_dynamic": {"desc": {"text": "見て！[doge]", "rich_text_nodes": [{"type": "RICH_TEXT_NODE_TYPE_TEXT", "text": "見て！"}, {"type": "RICH_TEXT_NODE_TYPE_EMOJI", "text": "[doge]", "emoji": {"text": "[doge]", "icon_url": "//i0.hdslb.com/doge.png"}}]}, "major": None},
    "module_stat": {"like": {"count": "1.2万"}, "comment": {"count": 3}, "forward": {"count": 0}}},
    "orig": {"id_str": "2", "type": "DYNAMIC_TYPE_LIVE_RCMD", "modules": {"module_author": {"name": "B", "pub_ts": 1699990000},
        "module_dynamic": {"major": {"type": "MAJOR_TYPE_LIVE_RCMD", "live_rcmd": {"content": json.dumps({"live_play_info": {"title": "歌枠", "cover": "//x/c.jpg"}})}}}}}}
acc = _new_acc(); r = parse_item(item, acc)
check("forward parse", r["type"] == "forward" and r["text"] == "見て！[doge]" and r["stats"]["like"] == 12000 and r["orig"]["title"] == "歌枠" and r["orig"]["author"] == "B", r)
check("emote icon captured", acc["emote_icons"].get("[doge]") == "//i0.hdslb.com/doge.png")
# Retired backend caches remain readable and must not overwrite higher-quality translations.
r = {"id": "1", "text": "今日は配信します"}
check("keep LLM translation over machine", T._apply_better(r, True, T.QUALITY["microsoft"], {"1": {"zh": "今天直播", "backend": "ollama", "source_hash": T.source_hash(r)}}, {}) and r["zh"] == "今天直播" and r["tr"] == "ollama", r)
r = {"id": "2", "text": "今日は配信します"}
check("keep higher-ranked machine cache", T._apply_better(r, True, T.QUALITY["microsoft"], {}, {"deepl": {"今日は配信します": "今天要直播"}}) and r["tr"] == "deepl", r)
r = {"id": "3", "text": "今日は配信します"}
check("same-rank cache is not 'better'", not T._apply_better(r, True, T.QUALITY["microsoft"], {}, {"microsoft": {"今日は配信します": "x"}}), r)
r = {"id": "4", "text": "今日は配信します", "orig": {"text": "新グッズのお知らせ"}}
check("LLM note without forward translation is incomplete", not T._apply_better(r, True, T.QUALITY["microsoft"], {"4": {"zh": "今天直播", "backend": "ollama"}}, {}), r)

# Data merge driver keeps observations from multiple local updates.
from hinome import merge as M
a = {"1": {"item": {"v": "old"}, "first_seen": 5, "last_seen": 10}, "2": {"item": {}, "first_seen": 1, "last_seen": 3}}
b = {"1": {"item": {"v": "new"}, "first_seen": 7, "last_seen": 20}, "3": {"item": {}, "first_seen": 8, "last_seen": 8},
     "2": {"item": {}, "first_seen": 1, "last_seen": 2, "gone": 30}}
m = M.merge_raw(a, b)
check("merge raw keeps fresher item", m["1"]["item"]["v"] == "new" and m["1"]["first_seen"] == 5, m["1"])
check("merge raw union + gone wins when newer", set(m) == {"1", "2", "3"} and m["2"].get("gone") == 30, m)
m = M.merge_deep({"microsoft": {"a": "A"}}, {"microsoft": {"b": "B"}, "echo": {"c": "C"}})
check("merge translations union", m == {"microsoft": {"a": "A", "b": "B"}, "echo": {"c": "C"}}, m)
check("merge state max ts", M.merge_state({"last_crawl": 5, "fetcher": "raw"}, {"last_crawl": 9, "last_full_crawl": 1}) == {"last_crawl": 9, "fetcher": "raw", "last_full_crawl": 1})
out = M.merge_jsonl('{"ts": 1}\n{"ts": 3}\n', '{"ts": 1}\n{"ts": 2}\n')
check("merge jsonl union sorted", out == '{"ts": 1}\n{"ts": 2}\n{"ts": 3}\n', out)

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
