"""Offline translation regressions; fixtures never read or change the real archive."""
import copy
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hinome import local_mt as L, translate as T, merge as M
from hinome.util import DEFAULTS, load_json, save_json


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        sandbox = Path(__file__).parent / '.sandbox'
        sandbox.mkdir(exist_ok=True)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=sandbox)))
        for name in ('TR_CACHE_FILE', 'TR_REVIEW_FILE', 'LLM_CACHE_FILE'):
            self.stack.enter_context(patch.object(T, name, self.root / name))
        self.stack.enter_context(patch.object(T.time, 'sleep'))
        self.cfg = copy.deepcopy(DEFAULTS)

    def test_review_skips_machine_and_survives_rebuild(self):
        p = {'id': '1', 'text': '今日も配信する！'}
        save_json(T.TR_REVIEW_FILE, {'1': {'source_hash': T.source_hash(p), 'zh': '今天也直播！'}})
        with patch.object(T, 'pick_backend', side_effect=AssertionError('no machine needed')):
            stats = T.translate_posts([p], self.cfg)
        self.assertEqual((p['zh'], p['tr'], stats['reviewed']), ('今天也直播！', 'reviewed', 1))

    def test_source_edit_invalidates_review(self):
        p = {'id': '1', 'text': '今日も配信する！'}
        save_json(T.TR_REVIEW_FILE, {'1': {'source_hash': T.source_hash(p), 'zh': '今天也直播！'}})
        p['text'] = '今日は休み'
        T.translate_posts([p], self.cfg, 'none')
        self.assertNotIn('zh', p)
        self.assertTrue(p['review_stale'])

    def test_partial_review_does_not_hide_missing_title(self):
        p = {'id': '1', 'text': '今日は配信する', 'title': 'お知らせ'}
        save_json(T.TR_REVIEW_FILE, {'1': {'source_hash': T.source_hash(p), 'zh': '今天直播'}})
        T.translate_posts([p], self.cfg, 'none')
        self.assertEqual(p['zh'], '今天直播')
        self.assertNotIn('tr', p)
        self.assertEqual(p['reviewed_fields'], ['zh'])

    def test_full_document_cache_preserves_context(self):
        text = '今日は配信する\n返事を待ってください'
        self.assertEqual(T.assemble(text, {text: '今天直播\n请等我回复'}), '今天直播\n请等我回复')
        self.assertTrue(T._covered(text, {text: '今天直播\n请等我回复'}))

    def test_hymt_only_translates_new_or_changed_source(self):
        old = {'google': {'おはようございます': '早上好'}, 'hymt2': {'今日は休み': '今天休息'}}
        save_json(T.TR_CACHE_FILE, old)
        posts = [{'id': '1', 'text': 'おはようございます'}, {'id': '2', 'text': '今日は休み'},
                 {'id': '3', 'text': '明日は配信する'}]
        backend = T.HYMT({})
        backend.translate_batch = Mock(side_effect=lambda texts: ['新增译文：' + text for text in texts])
        with patch.object(T, 'pick_backend', return_value=backend):
            stats = T.translate_posts(copy.deepcopy(posts), self.cfg, 'hymt')
        backend.translate_batch.assert_called_once_with(['明日は配信する'])
        self.assertEqual((stats['cached'], stats['segments'], stats['failed']), (2, 1, 0))
        cache = load_json(T.TR_CACHE_FILE, {})
        for name, entries in old.items():
            self.assertLessEqual(entries.items(), cache[name].items())
        with patch.object(T, 'pick_backend', side_effect=AssertionError('cached run must not probe model')):
            rebuilt = copy.deepcopy(posts)
            T.translate_posts(rebuilt, self.cfg, 'hymt')
        self.assertEqual(rebuilt[0]['zh'], '早上好')
        self.assertEqual(rebuilt[1]['zh'], '今天休息')
        posts[2]['text'] = '明日は休み'
        backend.translate_batch.reset_mock()
        with patch.object(T, 'pick_backend', return_value=backend):
            T.translate_posts(copy.deepcopy(posts), self.cfg, 'hymt')
        backend.translate_batch.assert_called_once_with(['明日は休み'])
        self.assertLessEqual(cache['hymt2'].items(), load_json(T.TR_CACHE_FILE, {})['hymt2'].items())

    def test_hymt_failure_preserves_cache_and_retries_missing_text(self):
        old = {'hymt2': {'今日は休み': '今天休息', '明日は配信する': ''}}
        save_json(T.TR_CACHE_FILE, old)
        posts = [{'id': '1', 'text': '今日は休み'}, {'id': '2', 'text': '明日は配信する'}]
        backend = T.HYMT({})
        backend.translate_batch = Mock(side_effect=[[''], ['明天直播']])
        with patch.object(T, 'pick_backend', return_value=backend):
            stats = T.translate_posts(copy.deepcopy(posts), self.cfg, 'hymt')
            self.assertEqual(stats['failed'], 1)
            self.assertEqual(load_json(T.TR_CACHE_FILE, {}), old)
            stats = T.translate_posts(posts, self.cfg, 'hymt')
        self.assertEqual(stats['failed'], 0)
        self.assertEqual(posts[0]['zh'], '今天休息')
        self.assertEqual(posts[1]['zh'], '明天直播')
        self.assertEqual(backend.translate_batch.call_args_list[0].args, (['明日は配信する'],))
        self.assertEqual(backend.translate_batch.call_args_list[1].args, (['明日は配信する'],))

    def test_hymt_missing_title_keeps_cached_body_from_other_backend(self):
        save_json(T.TR_CACHE_FILE, {'google': {'今日は休み': '今天休息'}})
        post = {'id': '1', 'text': '今日は休み', 'title': 'お知らせ'}
        backend = T.HYMT({})
        backend.translate_batch = Mock(return_value=['通知'])
        with patch.object(T, 'pick_backend', return_value=backend):
            T.translate_posts([post], self.cfg, 'hymt')
        backend.translate_batch.assert_called_once_with(['お知らせ'])
        self.assertEqual((post['zh'], post['title_zh']), ('今天休息', '通知'))
        self.assertEqual(load_json(T.TR_CACHE_FILE, {})['google'], {'今日は休み': '今天休息'})
        for mode in ('none', 'hymt'):
            rebuilt = {'id': '1', 'text': '今日は休み', 'title': 'お知らせ'}
            with patch.object(T, 'pick_backend', side_effect=AssertionError('mixed cache must rebuild offline')):
                stats = T.translate_posts([rebuilt], self.cfg, mode)
            self.assertEqual((rebuilt['zh'], rebuilt['title_zh'], stats['failed']), ('今天休息', '通知', 0))

    def test_chunking_never_loses_text_or_splits_url(self):
        text = 'こんにちは。\n' * 8 + 'https://example.org/very-long-link\n' + 'こんにちは。' * 20
        chunks = list(T.document_chunks(text, 30))
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(any('https://example.org/very-long-link' in c for c in chunks))

    def test_failed_entry_keeps_successful_sibling(self):
        b = T.HYMT({})
        b.engine = Mock()
        b.engine.translate.side_effect = ['你好', ValueError('truncated')]
        self.assertEqual(b.translate_batch(['こんにちは', 'おはよう']), ['你好', ''])
        b.close()
        self.assertIsNone(b.engine)

    def test_interruption_closes_model(self):
        b = T.HYMT({})
        b.translate_batch = Mock(side_effect=KeyboardInterrupt)
        b.close = Mock()
        with patch.object(T, 'pick_backend', return_value=b), self.assertRaises(KeyboardInterrupt):
            T.translate_posts([{'id':'1','text':'今日は休み'}], self.cfg, 'hymt')
        b.close.assert_called_once()

    def test_truncated_output_not_accepted(self):
        engine = L.Translator()
        self.addCleanup(engine.close)
        engine.start = Mock()
        engine.url = 'http://127.0.0.1:1'
        engine.http = Mock()
        engine.http.post.return_value.json.return_value = {'choices':[{'finish_reason':'length', 'message':{'content':'今天'}}]}
        with self.assertRaises(ValueError):
            engine.translate('今日は配信する')

    def test_crashed_server_is_restarted_a_few_times(self):
        class Proc:
            code = None

            def poll(self):
                return self.code

            def terminate(self):
                self.code = -15

            def wait(self, timeout=None):
                return self.code

        procs = []

        def spawn(*args, **kwargs):
            procs.append(Proc()); return procs[-1]

        engine = L.Translator()
        self.addCleanup(engine.close)
        engine.http = Mock()
        engine.http.get.return_value.ok = True
        with patch.object(L, 'MODEL_DIR', self.root), patch.object(L, 'executable', return_value=self.root / 'llama-server'), \
                patch.object(L.subprocess, 'Popen', side_effect=spawn):
            (self.root / L.MODEL_NAME).write_bytes(b'')
            engine.start(); engine.start()
            self.assertEqual(len(procs), 1, 'a live server is reused')
            for _ in range(3):
                procs[-1].code = 1; engine.start()
            self.assertEqual(len(procs), 4, 'an exited server is started again')
            procs[-1].code = 1
            with self.assertRaises(RuntimeError):
                engine.start()

    def test_boilerplate_and_paragraph_spacing(self):
        engine = L.Translator()
        self.addCleanup(engine.close)
        engine.start = Mock()
        engine.url = 'http://127.0.0.1:1'
        engine.http = Mock()
        engine.http.post.return_value.json.return_value = {'choices':[{'finish_reason':'stop', 'message':{'content':'  谢谢  '}}]}
        self.assertEqual(engine.translate('\u200b今日もこの後から配信する！\n\nありがとう'), '今天也马上开播！\n\n谢谢')
        self.assertNotIn('低気圧', L.prompt('ありがとう'))
        self.assertEqual(engine.translate('今日の配信も22時からやる！！'), '今天的直播也从22点开始！')

    def test_missing_protected_token_is_flagged(self):
        self.assertIn('表情/链接/提及需复核', T.qa_flags({'text':'ありがとう[doge]', 'zh':'谢谢'}))

    def test_standalone_joiner_is_not_a_missing_emoji(self):
        self.assertNotIn('表情/链接/提及需复核', T.qa_flags({'text':'\u200dこんにちは', 'zh':'你好'}))
        self.assertNotIn('表情/链接/提及需复核', T.qa_flags({'text':'\u200d⛄ありがとう', 'zh':'⛄谢谢'}))

    def test_reviewed_name_can_keep_kana(self):
        self.assertNotIn('译文残留假名', T.qa_flags({'text':'マツコデラックスさん', 'zh':'マツコ・デラックス', 'reviewed_fields':['zh']}))

    def test_original_emote_repetition_is_kept(self):
        self.assertNotIn('译文异常重复', T.qa_flags({'text':'ありがとう'+'[doge]'*5, 'zh':'谢谢'+'[doge]'*5}))
        self.assertIn('译文异常重复', T.qa_flags({'text':'ありがとう', 'zh':'谢谢大家'*8}))

    def test_empty_cache_is_not_complete(self):
        self.assertFalse(T._covered('今日は休み', {'今日は休み':''}))

    def test_review_merge_keeps_hash_and_translation_together(self):
        a, b = self.root/'a.json', self.root/'b.json'
        save_json(a, {'1':{'source_hash':'old','zh':'旧译','title_zh':'旧标题','ts':1}})
        save_json(b, {'1':{'source_hash':'new','zh':'新译','ts':2}})
        M.merge_file(a,b,'translation_review.json')
        import json
        self.assertEqual(json.loads(a.read_text(encoding='utf-8'))['1'], {'source_hash':'new','zh':'新译','ts':2})


if __name__ == '__main__':
    unittest.main(verbosity=2)
