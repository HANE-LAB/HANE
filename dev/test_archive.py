"""Offline regressions for durable crawling and history. No real data or network."""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hinome import archive as A, fetch as F, translate as T, merge as M, live as V, analyze
from hinome import util as U
from hinome.util import load_config, load_json, save_json


def item(i, text="hello", likes=1):
    return {"id_str": str(i), "type": "DYNAMIC_TYPE_WORD", "modules": {
        "module_author": {"pub_ts": 1700000000, "mid": 2094031249},
        "module_dynamic": {"desc": {"text": text}}, "module_stat": {"like": {"count": likes}}}}


def page(items, more=False, offset=""):
    return {"items": items, "has_more": more, "offset": offset}


class Client:
    name = "fixture"

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def page(self, offset):
        self.calls.append(offset)
        result = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)

    def followers(self):
        return 123


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        sandbox = Path(__file__).resolve().parent / ".sandbox"
        sandbox.mkdir(exist_ok=True)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=sandbox)))
        for key in ("SESSIONS_FILE", "STATE_FILE", "SNAPSHOTS"):
            self.stack.enter_context(patch.object(V, key, self.root / ("live-" + key.lower())))
        for mod in (F, A):
            for key in ("RAW_FILE", "STATE_FILE", "HISTORY_FILE", "SNAPSHOTS", "METRICS", "MEDIA", "MEDIA_FILE"):
                if hasattr(mod, key):
                    self.stack.enter_context(patch.object(mod, key, self.root / key.lower()))
        self.stack.enter_context(patch.object(F.time, "sleep"))
        self.stack.enter_context(patch.object(F, "jitter_sleep"))
        self.cfg = load_config()
        self.stack.enter_context(patch.object(T, "TR_REVIEW_FILE", self.root / "reviews.json"))

    def crawl(self, pages, **kwargs):
        client = Client(pages)
        with patch.object(F, "make_client", return_value=(client, [])):
            result = F.crawl(self.cfg, **kwargs)
        return result, client

    def test_atomic_save_retries_temporary_file_lock(self):
        path = self.root / 'cache.json'
        save_json(path, {'old': 1})
        replace = U.os.replace
        calls = []
        def locked_once(src, dst):
            calls.append(1)
            if len(calls) == 1: raise PermissionError('file is open')
            return replace(src, dst)
        with patch.object(U.os, 'replace', side_effect=locked_once):
            save_json(path, {'new': 2})
        self.assertEqual(len(calls), 2)
        self.assertEqual(load_json(path, {}), {'new': 2})

    def test_atomic_save_keeps_both_versions_on_persistent_lock(self):
        path = self.root / 'cache.json'
        save_json(path, {'old': 1})
        with patch.object(U.os, 'replace', side_effect=PermissionError('locked')), self.assertRaises(PermissionError):
            save_json(path, {'new': 2})
        self.assertEqual(load_json(path, {}), {'old': 1})
        self.assertEqual(load_json(path.with_suffix('.json.tmp'), {}), {'new': 2})

    def test_failure_preserves_page_and_resumes(self):
        with self.assertRaises(RuntimeError):
            self.crawl([page([item(1)], True, "next"), RuntimeError("offline")])
        self.assertIn("1", load_json(F.RAW_FILE, {}))
        self.assertEqual(load_json(F.STATE_FILE, {})["checkpoint"]["offset"], "next")
        result, client = self.crawl([page([item(1)], True, "next"), page([item(2)])])
        self.assertEqual(client.calls, ["", "next", "next"])
        self.assertTrue(result["complete"])
        self.assertEqual(set(load_json(F.RAW_FILE, {})), {"1", "2"})

    def test_cap_is_not_completion_and_next_run_finishes_history(self):
        result, _ = self.crawl([page([item(1)], True, "next")], max_pages=1)
        self.assertFalse(result["complete"])
        self.assertFalse(load_json(F.STATE_FILE, {}).get("history_complete"))
        self.crawl([page([item(1)], True, "next"), page([item(2)])])
        self.assertTrue(load_json(F.STATE_FILE, {})["history_complete"])

    def test_malformed_empty_never_marks_gone_or_complete(self):
        save_json(F.RAW_FILE, {"1": {"item": item(1), "first_seen": 1, "last_seen": 1}})
        with self.assertRaises(ValueError):
            self.crawl([{}], full=True)
        self.assertNotIn("gone", load_json(F.RAW_FILE, {})["1"])
        self.assertFalse(load_json(F.STATE_FILE, {}).get("history_complete"))

    def test_transient_empty_terminal_is_retried(self):
        result, client = self.crawl([page([item(1)], True, "next"), page([]), page([item(2)])])
        self.assertEqual(result["total"], 2)
        self.assertEqual(client.calls, ["", "next", "next", "next"])

    def test_first_page_empty_is_never_success(self):
        with self.assertRaises(ValueError):
            self.crawl([page([])])

    def test_old_unverified_full_timestamp_is_not_trusted(self):
        save_json(F.RAW_FILE, {"1": {"item": item(1), "first_seen": 1, "last_seen": 1}})
        save_json(F.STATE_FILE, {"last_full_crawl": 9999999999})
        result, _ = self.crawl([page([item(1)], True, "next"), page([item(2)])])
        self.assertEqual(result["mode"], "全量")
        self.assertIn("2", load_json(F.RAW_FILE, {}))

    def test_repeated_cursor_fails_but_previous_page_is_saved(self):
        with self.assertRaises(ValueError):
            self.crawl([page([item(1)], True, "next"), page([item(2)], True, "next")])
        self.assertIn("1", load_json(F.RAW_FILE, {}))

    def test_raw_versions_and_metrics_survive_updates(self):
        A.observe(item(1, "before", 10), 1700000000)
        A.observe(item(1, "after", 20), 1700003600)
        A.observe(item(1, "after", 20), 1700007200)
        self.assertEqual(len(list(A.SNAPSHOTS.glob("*/*.json"))), 2)
        history = A.histories()["1"]
        self.assertEqual([r["text"] for r in history["revisions"]], ["before", "after"])
        self.assertEqual([r["stats"]["like"] for r in history["observations"]], [10, 20, 20])

    def test_content_reverted_to_old_version_remains_in_timeline(self):
        A.observe(item(1, "before", 10), 1700000000)
        A.observe(item(1, "after", 20), 1700003600)
        A.observe(item(1, "before", 10), 1700007200)
        self.assertEqual([r["text"] for r in A.histories()["1"]["revisions"]], ["before", "after", "before"])

    def test_corrupt_json_stops_without_renaming_or_overwriting(self):
        F.RAW_FILE.write_text('{broken', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.crawl([page([item(1)])])
        self.assertEqual(F.RAW_FILE.read_text(), '{broken')

    def test_media_only_allows_public_bilibili_https_cdn(self):
        self.assertTrue(A.safe_image_url("https://i0.hdslb.com/bfs/x.jpg"))
        for url in ("http://i0.hdslb.com/x", "https://hdslb.com.evil.test/x", "https://127.0.0.1/x", "https://u:p@i0.hdslb.com/x"):
            self.assertFalse(A.safe_image_url(url))

    def test_repeated_empty_after_saved_page_stays_incomplete(self):
        with self.assertRaises(ValueError):
            self.crawl([page([item(1)], True, "next"), page([])])
        state = load_json(F.STATE_FILE, {})
        self.assertEqual(state["checkpoint"]["offset"], "next")
        self.assertFalse(state.get("history_complete"))
        self.assertEqual(state["last_result"]["status"], "failed")

    def test_missing_needs_two_complete_scans_and_raw_is_kept(self):
        self.crawl([page([item(1), item(2)])])
        self.crawl([page([item(2)])], full=True)
        self.assertNotIn("gone", load_json(F.RAW_FILE, {})["1"])
        with patch.object(F, "now", return_value=2000000000):
            self.crawl([page([item(2)])], full=True)
        self.assertTrue(load_json(F.RAW_FILE, {})["1"].get("gone"))
        self.assertTrue(list(A.SNAPSHOTS.glob("1/*.json")))

    def test_truncated_list_never_marks_older_posts_gone(self):
        def dated(i, ts):
            it = item(i); it["modules"]["module_author"]["pub_ts"] = ts; return it
        self.crawl([page([dated(3, 1700000300), dated(2, 1700000200), dated(1, 1700000100)])])
        for stamp in (2000000000, 2100000000):   # a visitor list that stops early, twice
            with patch.object(F, "now", return_value=stamp):
                self.crawl([page([dated(2, 1700000200)])], full=True)
        raw = load_json(F.RAW_FILE, {})
        self.assertNotIn("gone", raw["1"], "older than anything the traversal reached: not checked")
        self.assertNotIn("missing_full_runs", raw["1"])
        self.assertTrue(raw["3"].get("gone"), "a newer post missing from two complete scans is still marked")

    def test_list_of_only_pinned_posts_marks_nothing_gone(self):
        pinned = item(9)
        pinned["modules"]["module_tag"] = {"text": "置顶"}
        self.crawl([page([pinned, item(1), item(2)])])
        for stamp in (2000000000, 2100000000):   # a restricted response that only returns the pinned post
            with patch.object(F, "now", return_value=stamp):
                self.crawl([page([pinned])], full=True)
        raw = load_json(F.RAW_FILE, {})
        self.assertFalse(any(raw[i].get("gone") or raw[i].get("missing_full_runs") for i in ("1", "2")))

    def test_rate_limit_stops_without_retrying_or_switching(self):
        built = []

        class Spare(Client):
            def __init__(self, *args):
                built.append(args)
                super().__init__([page([item(1)])])

        class Counted(Client):
            asked = 0

            def followers(self):
                Counted.asked += 1
                return 1

        client = Counted([F.BiliError(-412, "HTTP 412")])
        with patch.object(F, "make_client", return_value=(client, [Spare])), self.assertRaises(F.BiliError):
            F.crawl(self.cfg)
        self.assertEqual(len(client.calls), 1, "one blocked request, no retries")
        self.assertEqual(built, [], "no switch to another client")
        self.assertEqual(Counted.asked, 0, "no extra follower request while throttled")
        self.assertEqual(load_json(F.STATE_FILE, {})["last_result"]["status"], "failed")

    def test_wrong_author_rejected(self):
        wrong = item(1)
        wrong["modules"]["module_author"]["mid"] = 123
        with self.assertRaises(ValueError):
            self.crawl([page([wrong])])
        self.assertFalse(F.RAW_FILE.exists())

    def test_state_checkpoint_merge_is_atomic(self):
        old = {"schema_version": 3, "last_attempt": 1, "history_complete": True}
        new = {"schema_version": 3, "last_attempt": 2, "checkpoint": {"offset": "next"}, "history_complete": False}
        self.assertEqual(M.merge_state(old, new), new)
        self.assertEqual(M.merge_state(new, old), new)

    def test_edited_source_invalidates_llm_translation_and_analysis(self):
        post = {"id": "1", "text": "今日は配信します", "type": "text"}
        note = {"source_hash": T.source_hash(post), "zh": "今天直播", "tags": ["直播预告"]}
        self.assertTrue(T._llm_done(post, {"1": note}, True))
        post["text"] = "今日はお休み"
        self.assertFalse(T._llm_done(post, {"1": note}, True))

    def test_preview_with_thanks_still_detects_upcoming_stream(self):
        self.assertTrue(analyze.is_preview("今日もこの後から配信する！\n皆さん連日メッセージありがとうございます！"))
        self.assertFalse(analyze.is_preview("今日も配信来てくれてありがとう！"))

    def test_incomplete_translation_batch_is_not_cached(self):
        for key in ("TR_CACHE_FILE", "LLM_CACHE_FILE"):
            self.stack.enter_context(patch.object(T, key, self.root / key.lower()))
        backend = T.Echo(self.cfg["translate"])
        backend.translate_batch = lambda texts: []
        posts = [{"id": "1", "text": "今日は配信します"}]
        with patch.object(T, "pick_backend", return_value=backend):
            stats = T.translate_posts(posts, self.cfg, "echo")
        self.assertGreater(stats["failed"], 0)
        self.assertFalse(posts[0].get("tr"))
        self.assertEqual(load_json(T.TR_CACHE_FILE, {})["echo"], {})

    def test_cached_translation_needs_no_backend_probe(self):
        for key in ("TR_CACHE_FILE", "LLM_CACHE_FILE"):
            self.stack.enter_context(patch.object(T, key, self.root / key.lower()))
        save_json(T.TR_CACHE_FILE, {"argos": {"今日は配信します": "今天直播"}})
        posts = [{"id": "1", "text": "今日は配信します"}]
        with patch.object(T, "pick_backend", side_effect=AssertionError("must stay offline")):
            stats = T.translate_posts(posts, self.cfg, "none")
        self.assertEqual(posts[0]["zh"], "今天直播")
        self.assertEqual(stats["failed"], 0)

    def test_empty_translation_does_not_discard_valid_batch_entries(self):
        for key in ("TR_CACHE_FILE", "LLM_CACHE_FILE"):
            self.stack.enter_context(patch.object(T, key, self.root / key.lower()))
        backend = T.Echo(self.cfg["translate"])
        backend.translate_batch = lambda texts: ["你好", ""]
        posts = [{"id": "1", "text": "こんにちは"}, {"id": "2", "text": "おはよう"}]
        with patch.object(T, "pick_backend", return_value=backend):
            stats = T.translate_posts(posts, self.cfg, "echo")
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(posts[0]["zh"], "你好")
        self.assertFalse(posts[1].get("tr"))
        self.assertEqual(load_json(T.TR_CACHE_FILE, {})["echo"], {"こんにちは": "你好"})

    def test_torn_jsonl_tail_cannot_swallow_next_observation(self):
        from hinome.util import append_jsonl, read_jsonl
        path = self.root / "torn.jsonl"
        path.write_text('{"ts": 1}\n{bad', encoding="utf-8")
        append_jsonl(path, {"ts": 2})
        self.assertEqual(read_jsonl(path), [{"ts": 1}, {"ts": 2}])
        self.assertIn("{bad\n", path.read_text())

    def test_image_http_source_is_downloaded_over_https_and_saved_atomically(self):
        class Response:
            is_redirect = False
            headers = {"Content-Type": "image/png"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_content(self, size):
                from io import BytesIO
                from PIL import Image
                buf = BytesIO()
                Image.new("RGB", (1, 1)).save(buf, format="PNG")
                return [buf.getvalue()]
        from unittest.mock import Mock
        session = Mock()
        session.get.return_value = Response()
        name = A.download_image(session, "http://i0.hdslb.com/bfs/fixture.png")
        self.assertEqual(session.get.call_args.args[0], "https://i0.hdslb.com/bfs/fixture.png")
        self.assertTrue((A.MEDIA / name).read_bytes().startswith(b"\x89PNG"))
        self.assertFalse(list(A.MEDIA.glob("*.tmp")))

    def test_build_publishes_local_images_and_every_follower_snapshot(self):
        from hinome import build as B
        from hinome.util import append_jsonl
        for key in ("SITE", "HISTORY_FILE", "RUNLOG_FILE", "STATE_FILE"):
            self.stack.enter_context(patch.object(B, key, self.root / key.lower()))
        self.stack.enter_context(patch.object(B, "MEDIA", A.MEDIA))
        self.stack.enter_context(patch.object(B, "MEDIA_FILE", A.MEDIA_FILE))
        A.MEDIA.mkdir()
        (A.MEDIA / "fixture.png").write_bytes(b"fixture")
        save_json(A.MEDIA_FILE, {"https://i0.hdslb.com/x.png": {"file": "fixture.png"}})
        for ts in range(501):
            append_jsonl(B.HISTORY_FILE, {"ts": ts, "followers": ts})
        post = {"id": "1", "text": "</script><script>bad()</script>", "ts": 1}
        forwarded = {"id": "2", "text": "中文", "orig": {"text": "ありがとう"}, "orig_zh": "谢谢"}
        partial = {"id": "3", "text": "ありがとう", "zh": "谢谢", "title": "こんにちは"}
        out = B.build_site([post, forwarded, partial], {}, self.cfg, [])
        payload = load_json(B.SITE / "data.json", {})
        self.assertEqual(len(payload["history"]), 501)
        self.assertEqual(payload["meta"]["translation_needed"], 3)
        self.assertEqual(payload["meta"]["translation_done"], 1)
        self.assertEqual(payload["local_images"]["https://i0.hdslb.com/x.png"], "media/fixture.png")
        self.assertTrue((B.SITE / "media/fixture.png").exists())
        self.assertNotIn(post["text"], out.read_text(encoding="utf-8"))

    def test_release_omits_diagnostics_and_dev_is_separate(self):
        from hinome import build as B
        for key in ("SITE", "HISTORY_FILE", "RUNLOG_FILE", "STATE_FILE", "MEDIA", "MEDIA_FILE"):
            self.stack.enter_context(patch.object(B, key, self.root / key.lower()))
        save_json(B.STATE_FILE, {"last_result": {"status": "failed", "error": "PRIVATE_TEST_DIAGNOSTIC"}})
        post = {"id": "1", "ts": 1, "text": "普通原文 <!--DEV-->保留用户原文<!--/DEV-->"}
        self.cfg["output"]["edition"] = "release"
        release = B.build_site([post], {}, self.cfg, [], demo=True)
        html = release.read_text(encoding="utf-8")
        data = load_json(release.parent / "data.json", {})
        self.assertEqual(data["meta"]["edition"], "release")
        # the page carries the data deflated + base64 (no readable text in the source), and it unpacks to the same posts
        import base64, re, zlib
        self.assertNotIn("普通原文", html)
        packed = json.loads(zlib.decompress(base64.b64decode(re.search(r'await unpack\("([A-Za-z0-9+/=]+)"\)', html).group(1))))
        self.assertEqual(packed["posts"][0]["text"], post["text"])
        self.assertEqual(data["posts"][0]["text"], post["text"])
        self.assertNotIn("runs", data)
        self.assertNotIn("last_fetch", data["meta"])
        for text in ('id="archive-status"', 'data-v="pipeline"', 'id="shrine-story"', 'PRIVATE_TEST_DIAGNOSTIC', 'DYNAMIC LAB'):
            self.assertNotIn(text, html)
        self.cfg["output"]["edition"] = "dev"
        dev = B.build_site([post], {}, self.cfg, [], demo=True)
        self.assertEqual(dev.parent.name, "site-dev")
        self.assertNotEqual(dev, release)
        self.assertEqual(release.read_text(encoding="utf-8"), html)
        self.assertIn('data-v="pipeline"', dev.read_text(encoding="utf-8"))
        self.assertIn('PRIVATE_TEST_DIAGNOSTIC', dev.read_text(encoding="utf-8"))
        self.cfg["output"]["edition"] = "../../bad"
        with self.assertRaises(ValueError):
            B.build_site([post], {}, self.cfg, [], demo=True)

    def test_actual_git_merge_retains_both_sides_and_one_checkpoint(self):
        import os
        import shutil
        import subprocess
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        repo = Path(__file__).resolve().parent.parent
        env = {**os.environ, "PYTHONPATH": str(repo)}
        def git(*args):
            result = subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout
        git("init", "-b", "main")
        git("config", "user.name", "Archive Test")
        git("config", "user.email", "archive-test@example.invalid")
        git("config", "merge.hinome-data.driver", f'"{Path(sys.executable).as_posix()}" -m hinome.merge %O %A %B %P')
        shutil.copy2(repo / ".gitattributes", self.root / ".gitattributes")
        shutil.copy2(repo / ".gitignore", self.root / ".gitignore")
        data = self.root / "data"
        save_json(data / "raw_items.json", {})
        save_json(data / "state.json", {"schema_version": 4})
        (data / "metrics").mkdir()
        metric = data / "metrics/2026-10.jsonl"
        metric.write_text('{"ts": 1}\n')
        git("add", ".")
        git("commit", "-m", "base")
        git("checkout", "-b", "other")
        save_json(data / "raw_items.json", {"1": {"item": item(1), "last_seen": 10}})
        save_json(data / "state.json", {"schema_version": 4, "last_attempt": 10, "history_complete": True})
        metric.write_text('{"ts": 1}\n{"ts": 2}\n')
        git("add", ".")
        git("commit", "-m", "other archive")
        git("checkout", "main")
        save_json(data / "raw_items.json", {"2": {"item": item(2), "last_seen": 20}})
        save_json(data / "state.json", {"schema_version": 4, "last_attempt": 20, "checkpoint": {"offset": "next"}})
        metric.write_text('{"ts": 1}\n{"ts": 3}\n')
        git("add", ".")
        git("commit", "-m", "local archive")
        git("merge", "other", "--no-edit")
        self.assertEqual(set(load_json(data / "raw_items.json", {})), {"1", "2"})
        state = load_json(data / "state.json", {})
        self.assertNotIn("history_complete", state)
        self.assertEqual(state["checkpoint"]["offset"], "next")
        self.assertEqual([json.loads(row)["ts"] for row in metric.read_text().splitlines()], [1, 2, 3])
        self.assertIn("config.local.toml", git("check-ignore", "config.local.toml"))


class CliTests(unittest.TestCase):
    def test_publish_stops_after_pulling_new_code(self):
        import argparse
        import shutil
        import subprocess
        from hinome import cli as C
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        sandbox = Path(__file__).resolve().parent / ".sandbox"
        sandbox.mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(dir=sandbox))
        self.addCleanup(shutil.rmtree, root, True)

        def git(cwd, *args):
            result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        git(root, "init", "--bare", "-b", "main", "remote.git")
        for name in ("mine", "other"):
            git(root, "clone", "-q", "remote.git", name)
            git(root / name, "config", "user.name", "Publish Test")
            git(root / name, "config", "user.email", "publish-test@example.invalid")
        (root / "mine/data").mkdir(); (root / "mine/data/state.json").write_text("{}")
        (root / "mine/hinome").mkdir(); (root / "mine/hinome/x.py").write_text("A = 1\n")
        git(root / "mine", "add", "."); git(root / "mine", "commit", "-qm", "base"); git(root / "mine", "push", "-q", "origin", "main")
        git(root / "other", "pull", "-q", "origin", "main")
        args = argparse.Namespace(no_open=True, full=False, max_pages=None, backend="none", verbose=False)
        for path, expect_update in (("data/state.json", True), ("hinome/x.py", False)):
            (root / "other" / path).write_text((root / "other" / path).read_text() + "\n")
            git(root / "other", "commit", "-qam", "remote change"); git(root / "other", "push", "-q", "origin", "main")
            update = unittest.mock.Mock(return_value=0)
            with patch.object(C, "ROOT", root / "mine"), patch.object(C, "cmd_update", update):
                code = C.cmd_publish(args, {})
            self.assertEqual(update.called, expect_update, path)
            self.assertEqual(code, 0 if expect_update else 2)

    def test_legacy_console_encoding_does_not_abort_command(self):
        import os
        import subprocess

        script = """
import sys
from unittest.mock import patch
from hinome.cli import main
from hinome.util import DEFAULTS, ok, err
def command(args, cfg):
    ok('中文 ✓')
    err('中文 ✗')
    print('中文 ✓', file=sys.stderr)
    return 0
with patch('hinome.cli.load_config', return_value=DEFAULTS), patch('hinome.cli.cmd_doctor', command):
    raise SystemExit(main(['doctor']))
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONIOENCODING": "gbk:strict", "PYTHONUTF8": "0"},
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn("中文 ✓", result.stdout.decode("utf-8"))
        self.assertIn("中文 ✗", result.stdout.decode("utf-8"))
        self.assertIn("中文 ✓", result.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
