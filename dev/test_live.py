"""Offline live archive regressions; all sessions and storage are fictional."""
import copy
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hinome import live as L, merge as M
from hinome.util import load_json


def session(i=1, **values):
    return {"liveId": f"00000000-0000-4000-8000-{i:012d}", "startDate": 1700000000000,
            "stopDate": 1700003600000, "isFinish": True, "isFull": True,
            "totalIncome": 12.34, "danmakusCount": 15, "maxOnlineCount": 0, **values}


def response(*items):
    return {"code": 200, "data": {"channel": {"uId": 7, "roomId": 8, "totalLiveCount": len(items)}, "lives": list(items)}}


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        sandbox = Path(__file__).resolve().parent / ".sandbox"; sandbox.mkdir(exist_ok=True)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=sandbox)))
        for key in ("SESSIONS_FILE", "STATE_FILE", "SNAPSHOTS"):
            self.stack.enter_context(patch.object(L, key, self.root / key.lower()))

    def test_units_and_missing_are_distinct_from_zero(self):
        r = L.normalize(session(totalIncome=0), 7)
        self.assertEqual(r["duration"], 3600)
        self.assertEqual(r["revenue_cents"], 0)
        self.assertIsNone(r["watch"])
        self.assertIsNone(r["peak"])
        self.assertEqual(L.normalize(session(), 7)["revenue_cents"], 1234)
        self.assertIsNone(L.normalize(session(totalIncome=None), 7)["revenue_cents"])

    def test_invalid_end_and_ongoing_are_not_fabricated_durations(self):
        for s in [session(stopDate=1), session(isFinish=False), session(stopDate=None)]:
            self.assertIsNone(L.normalize(s, 7)["duration"])
            self.assertIsNone(L.normalize(s, 7)["end"])

    def test_bad_responses_never_replace_archive(self):
        L.ingest(response(session()), 7, 10)
        old = L.SESSIONS_FILE.read_bytes()
        bad_uid = response(session()); bad_uid["data"]["channel"]["uId"] = 9
        bad_count = response(session()); bad_count["data"]["channel"]["totalLiveCount"] = 3
        for body in [bad_uid, bad_count, response(session(), session()), response(),
                     response(session(liveId="../../bad")), response(session(startDate=float("nan"))),
                     {"code": 200, "data": {}}, {"code": 403}]:
            with self.assertRaises((ValueError, KeyError, TypeError)):
                L.ingest(body, 7, 20)
            self.assertEqual(L.SESSIONS_FILE.read_bytes(), old)

    def test_revisions_and_disappeared_sessions_are_preserved(self):
        a, b = session(), session(2)
        L.ingest(response(a, b), 7, 10)
        L.ingest(response(a, b), 7, 20)
        self.assertEqual(len(list((L.SNAPSHOTS / "7" / a["liveId"]).glob("*.json"))), 1)
        a["totalIncome"] = 20
        st = L.ingest(response(a), 7, 30)
        self.assertEqual(st, {"total": 2, "source_count": 1, "new": 0, "changed": 1})
        records = {x["id"]: x for x in L.payload(7)["sessions"]}
        self.assertTrue(records[b["liveId"]]["source_missing"])
        self.assertEqual(records[a["liveId"]]["first_seen"], 10)
        self.assertEqual(len(list((L.SNAPSHOTS / "7" / a["liveId"]).glob("*.json"))), 2)
        L.ingest(response(a, b), 7, 40)
        self.assertFalse(any(x["source_missing"] for x in L.payload(7)["sessions"]))

    def test_nested_versions_are_not_counted_twice_or_published(self):
        s = session(); s["versions"] = [{"live": copy.deepcopy(s), "userName": "fictional uploader"}]
        L.ingest(response(s), 7, 10)
        p = L.payload(7)
        self.assertEqual(len(p["sessions"]), 1)
        self.assertNotIn("versions", p["sessions"][0])
        self.assertNotIn("fictional uploader", json.dumps(p))
        self.assertEqual(L.payload(9)["sessions"], [])

    def test_failure_preserves_sessions_and_exposes_staleness(self):
        L.ingest(response(session()), 7, 10); old = L.SESSIONS_FILE.read_bytes()
        with patch("requests.Session") as http:
            http.return_value.__enter__.return_value.get.side_effect = RuntimeError("offline")
            with self.assertRaises(RuntimeError): L.crawl({"target": {"uid": 7}})
        self.assertEqual(L.SESSIONS_FILE.read_bytes(), old)
        self.assertEqual(L.payload(7)["status"], "failed")
        self.assertEqual(L.payload(7)["last_success"], 10)

    def test_git_merge_keeps_whole_fresher_record(self):
        a, b = self.root / "a.json", self.root / "b.json"
        a.write_text(json.dumps({"x": {"item": {"totalIncome": 10}, "first_seen": 1, "last_seen": 2}}))
        b.write_text(json.dumps({"x": {"item": {"totalIncome": 5}, "first_seen": 2, "last_seen": 3}}))
        M.merge_file(a, b, "live_sessions.json")
        self.assertEqual(load_json(a, {})["x"], {"item": {"totalIncome": 5}, "first_seen": 1, "last_seen": 3})


if __name__ == "__main__": unittest.main(verbosity=2)
