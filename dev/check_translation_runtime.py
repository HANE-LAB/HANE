"""显式运行真实 Hy-MT：只写隔离样例，记录新译、缓存命中与原文变更耗时。"""
import copy
import json
import os
import re
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hinome import translate as T
from hinome.util import DEFAULTS, load_json, save_json


def main():
    sandbox = Path(__file__).parent / '.sandbox'
    sandbox.mkdir(exist_ok=True)
    with ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=sandbox)))
        for name in ('TR_CACHE_FILE', 'TR_REVIEW_FILE', 'LLM_CACHE_FILE'):
            stack.enter_context(patch.object(T, name, root / name))
        posts = [
            {'id': 'old', 'text': 'おはようございます'},
            {'id': 'reviewed', 'text': 'いつも応援してくれてありがとう'},
            {'id': 'new-1', 'text': '明日の配信は午後八時からです。遊びに来てください。'},
            {'id': 'new-2', 'text': '今日は新しいゲームを練習しました。難しかったけれど、とても楽しかったです。'},
        ]
        save_json(T.TR_CACHE_FILE, {'google': {posts[0]['text']: '早上好（保留旧译）'}})
        save_json(T.TR_REVIEW_FILE, {'reviewed': {'source_hash': T.source_hash(posts[1]), 'zh': '谢谢一直以来的支持（校订）'}})
        review_bytes = T.TR_REVIEW_FILE.read_bytes()
        original_batch = T.HYMT.translate_batch
        requests = []

        def counted(backend, texts):
            requests.extend(texts)
            return original_batch(backend, texts)

        stack.enter_context(patch.object(T.HYMT, 'translate_batch', counted))
        reports = []
        for phase, expected in (('新增内容', 2), ('重复运行', 0), ('原文变更', 1)):
            if phase == '原文变更':
                posts[2]['text'] = '明日の配信は午後九時からです。開始時間を一時間遅らせます。'
            requests.clear()
            before = load_json(T.TR_CACHE_FILE, {})
            records = copy.deepcopy(posts)
            start = time.perf_counter()
            stats = T.translate_posts(records, copy.deepcopy(DEFAULTS), 'hymt')
            elapsed = time.perf_counter() - start
            assert stats['failed'] == 0, stats
            assert len(requests) == expected, (phase, requests)
            if expected:
                assert requests == [p['text'] for p in (posts[2:] if expected == 2 else posts[2:3])]
            assert records[0]['zh'] == '早上好（保留旧译）'
            assert records[1]['zh'] == '谢谢一直以来的支持（校订）'
            assert T.TR_REVIEW_FILE.read_bytes() == review_bytes
            for record in records[2:]:
                assert record.get('zh') and record['zh'] != record['text']
                assert re.search('[\u4e00-\u9fff]', record['zh'])
            after = load_json(T.TR_CACHE_FILE, {})
            for name, entries in before.items():
                assert entries.items() <= after[name].items(), '旧译文缓存被覆盖'
            report = {'phase': phase, 'seconds': round(elapsed, 3), 'translated_fields': len(requests),
                      'samples': [{'source': r['text'], 'translation': r['zh']} for r in records[2:]]}
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as output:
                output.write('### Hy-MT 实测（隔离样例）\n\n| 阶段 | 实际送译字段 | 秒 |\n|---|---:|---:|\n')
                for report in reports:
                    output.write(f"| {report['phase']} | {report['translated_fields']} | {report['seconds']} |\n")
                output.write('\n旧译文、校订和历史缓存保留检查通过。耗时包含按需启动及退出模型。\n')


if __name__ == '__main__':
    main()
