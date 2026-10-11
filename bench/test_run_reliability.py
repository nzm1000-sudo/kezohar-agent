"""בדיקות אמינות לתשתית הבנצ'מרק (bench/run.py) — unittest בסטנדרט בלבד.

הכל אופליין: אין אינטרנט, אין NAS, אין LM Studio. כל הרשת ממוקת (mock).
הרצה:  python3 -m unittest bench.test_run_reliability -v
"""
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run as bench_run

DUMMY_BASE = "http://127.0.0.1:9/v1"


def _ok_response(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class TestPostResponses(unittest.TestCase):
    def setUp(self):
        bench_run.BASE = DUMMY_BASE

    def test_valid_http_response(self):
        payload = {"choices": [{"message": {"content": "שלום"}}]}
        with patch.object(bench_run.urllib.request, "urlopen", return_value=_ok_response(payload)):
            out = bench_run.post("/chat/completions", {"model": "m"})
        self.assertEqual(out, payload)

    def test_http_error(self):
        err = urllib.error.HTTPError(DUMMY_BASE, 500, "boom", {}, io.BytesIO(b""))
        with patch.object(bench_run.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(bench_run.BenchmarkConnectionError) as cm:
                bench_run.post("/chat/completions", {})
        self.assertIn("500", str(cm.exception))

    def test_timeout_direct(self):
        with patch.object(bench_run.urllib.request, "urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(bench_run.BenchmarkConnectionError) as cm:
                bench_run.post("/chat/completions", {}, timeout=1)
        self.assertIn("נכשל", str(cm.exception))

    def test_timeout_as_urlerror(self):
        err = urllib.error.URLError(socket.timeout("timed out"))
        with patch.object(bench_run.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(bench_run.BenchmarkConnectionError) as cm:
                bench_run.post("/chat/completions", {}, timeout=1)
        self.assertIn("timeout", str(cm.exception).lower())

    def test_invalid_json(self):
        with patch.object(bench_run.urllib.request, "urlopen",
                           return_value=io.BytesIO("לא json תקין{{{".encode("utf-8"))):
            with self.assertRaises(bench_run.BenchmarkConnectionError) as cm:
                bench_run.post("/chat/completions", {})
        self.assertIn("JSON", str(cm.exception))

    def test_server_unreachable(self):
        err = urllib.error.URLError(ConnectionRefusedError("refused"))
        with patch.object(bench_run.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(bench_run.BenchmarkConnectionError) as cm:
                bench_run.post("/chat/completions", {})
        self.assertIn("אינו עונה", str(cm.exception))

    def test_malformed_chat_shape(self):
        payload = {"oops": 1}
        with patch.object(bench_run.urllib.request, "urlopen", return_value=_ok_response(payload)):
            with self.assertRaises(bench_run.BenchmarkConnectionError):
                bench_run.tool_test("m", {"q": "מה מברכים על אורז?", "tags": ["src"]})


class TestConfigFile(unittest.TestCase):
    def test_missing_config_file(self):
        with self.assertRaises(SystemExit) as cm:
            bench_run.env("LLM_BASE_URL", path="/nonexistent-dir-xyz/.env")
        self.assertIn("חסר", str(cm.exception))

    def test_missing_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# הערה\nOTHER=1\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                bench_run.env("LLM_BASE_URL", path=str(p))
        self.assertIn("LLM_BASE_URL", str(cm.exception))

    def test_comments_quotes_and_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# הערה\n\nLLM_BASE_URL = 'http://x:1234/v1' \n", encoding="utf-8")
            self.assertEqual(bench_run.env("LLM_BASE_URL", path=str(p)), "http://x:1234/v1")


class TestHebrewSentences(unittest.TestCase):
    def test_two_hebrew_sentences(self):
        parts = bench_run.split_sentences("מותר לאכול דג עם חלב? כן, מותר.")
        self.assertEqual(len(parts), 2)

    def test_sof_pasuq_ends_sentence(self):
        self.assertTrue(bench_run.SENT_END.search("פסוק׃ המשך"))
        parts = bench_run.split_sentences("פסוק ראשון׃ פסוק שני׃")
        self.assertEqual(len(parts), 2)

    def test_ellipsis_ends_sentence(self):
        parts = bench_run.split_sentences("אולי… כן.")
        self.assertEqual(len(parts), 2)

    def test_citation_colon_does_not_split(self):
        parts = bench_run.split_sentences("שולחן ערוך רח:ז הוא המקור. זו תשובה.")
        self.assertEqual(len(parts), 2)

    def test_english_still_works(self):
        parts = bench_run.split_sentences("Hello world. Second one!")
        self.assertEqual(len(parts), 2)


class TestCitations(unittest.TestCase):
    def setUp(self):
        self.ctx = [{"he_ref": "שולחן ערוך, אורח חיים רח:ז"}]

    def test_exact_match_preserved(self):
        self.assertTrue(bench_run.cites_source("(שולחן ערוך, אורח חיים רח:ז)", self.ctx))

    def test_normalized_geresh_variant(self):
        self.assertTrue(bench_run.cites_source("שולחן ערוך אורח חיים רח ז", self.ctx))

    def test_sof_pasuq_colon_variant(self):
        self.assertTrue(bench_run.cites_source("אורח חיים רח׃ז", self.ctx))

    def test_spelled_out_siman_seif(self):
        self.assertTrue(bench_run.cites_source("סימן רח סעיף ז", self.ctx))

    def test_no_false_positive(self):
        self.assertFalse(bench_run.cites_source("אין כאן שום מראה מקום", self.ctx))

    def test_empty_inputs(self):
        self.assertFalse(bench_run.cites_source("", self.ctx))
        self.assertFalse(bench_run.cites_source("רח:ז", []))
        self.assertFalse(bench_run.cites_source("רח:ז", None))


class FakeStream:
    """Minimal streaming-response double: read(n) chunks + close tracking."""

    def __init__(self, payloads):
        self._data = b"".join(payloads)
        self._pos = 0
        self.closed = False

    def read(self, n=-1):
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos:self._pos + n if n and n > 0 else len(self._data)]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class TestStreamRobustness(unittest.TestCase):
    def sse(self, text):
        return ('data: {"choices": [{"delta": {"content": %s}}]}'
                % json.dumps(text, ensure_ascii=False)).encode("utf-8") + b"\n"

    def test_corrupt_sse_chunk_skipped(self):
        stream = FakeStream([
            b"data: {oops bad json\n",
            self.sse("שלום."),
            b"data: [DONE]\n",
        ])
        with patch.object(bench_run, "post", return_value=stream):
            out = bench_run.answer_test(
                "m", {"q": "שלום?", "tags": ["src"]}, self_ctx())
        self.assertEqual(out["answer"], "שלום.")
        self.assertEqual(out["sentences"], 1)
        self.assertFalse(out["truncated"])
        self.assertTrue(stream.closed)

    def test_mid_answer_disconnect_keeps_partial(self):
        stream = FakeStream([self.sse("חלק ראשון. ")])
        with patch.object(bench_run, "post", return_value=stream), \
             patch.object(bench_run, "iter_sse_lines",
                          side_effect=_disconnect_after_first):
            out = bench_run.answer_test(
                "m", {"q": "שלום?", "tags": ["src"]}, self_ctx())
        self.assertTrue(out["truncated"])
        self.assertIn("נקטעה", out["answer"])
        self.assertIn("חלק ראשון", out["answer"])
        self.assertTrue(stream.closed)

    def test_utf8_split_across_reads_intact(self):
        full = self.sse("שלום עולם.") + b"data: [DONE]\n"
        halves = [full[:7], full[7:]]  # split inside a Hebrew char / JSON
        stream = FakeStream(halves)
        with patch.object(bench_run, "post", return_value=stream):
            out = bench_run.answer_test(
                "m", {"q": "שלום?", "tags": ["src"]}, self_ctx())
        self.assertIn("שלום עולם.", out["answer"])
        self.assertFalse(out["truncated"])

    def test_response_closed_on_success(self):
        payload = {"choices": [{"message": {"content": "x"}}]}
        stream = FakeStream([json.dumps(payload).encode("utf-8")])
        with patch.object(bench_run.urllib.request, "urlopen", return_value=stream):
            bench_run.post("/chat/completions", {"model": "m"})
        self.assertTrue(stream.closed)

    def test_corrupt_chunk_does_not_skew_timing_fields(self):
        stream = FakeStream([
            b"data: {oops bad json\n",
            self.sse("משפט ראשון. משפט שני."),
            b"data: [DONE]\n",
        ])
        with patch.object(bench_run, "post", return_value=stream):
            out = bench_run.answer_test(
                "m", {"q": "שלום?", "tags": ["src"]}, self_ctx())
        # corrupt chunk contributes no text/tokens: only real content counts
        self.assertEqual(out["sentences"], 2)
        self.assertEqual(out["answer"], "משפט ראשון. משפט שני.")


def _disconnect_after_first(resp):
    """Yields one real SSE line from resp, then simulates a network break."""
    yield "data: " + json.dumps(
        {"choices": [{"delta": {"content": "חלק ראשון. "}}]},
        ensure_ascii=False)
    try:
        resp.close()
    finally:
        raise ConnectionError("simulated mid-answer disconnect")


class TestCitationNoFalsePositives(unittest.TestCase):
    """Regression: partial siman/seif numbers must NOT match an unrelated source."""

    def test_short_siman_inside_long(self):
        ctx = [{"he_ref": "שולחן ערוך, אורח חיים ח:ז"}]  # siman 8
        # raw 'ח:ז' appears inside 'רח:ז' (208) — must not count
        self.assertFalse(bench_run.cites_source("כדברי רח:ז המפורש", ctx))

    def test_spelled_siman_substring(self):
        ctx = [{"he_ref": "שולחן ערוך, אורח חיים ח:ז"}]
        # 'סימן רח' contains ח but is siman 208, not 8
        self.assertFalse(bench_run.cites_source("ראה סימן רח סעיף ז", ctx))

    def test_spelled_seif_substring(self):
        ctx = [{"he_ref": "שולחן ערוך, אורח חיים רח:ז"}]
        # seif טז (16) ends with ז (7) but is not seif 7
        self.assertFalse(bench_run.cites_source("ראה סימן רח סעיף טז", ctx))

    def test_bare_number_no_separator(self):
        ctx = [{"he_ref": "שולחן ערוך, אורח חיים רח:ז"}]
        # 'רחז' without any separator is not a citation of רח:ז
        self.assertFalse(bench_run.cites_source("המילה רחז אינה מראה מקום", ctx))

    def test_correct_source_still_matches(self):
        ctx = [{"he_ref": "שולחן ערוך, אורח חיים רח:ז"}]
        self.assertTrue(bench_run.cites_source("כמבואר (שולחן ערוך, אורח חיים רח:ז)", ctx))
        self.assertTrue(bench_run.cites_source("ראה סימן רח סעיף ז", ctx))
        ctx8 = [{"he_ref": "שולחן ערוך, אורח חיים ח:ז"}]
        self.assertTrue(bench_run.cites_source("כמבואר (ח:ז)", ctx8))
        self.assertTrue(bench_run.cites_source("ראה סימן ח סעיף ז", ctx8))


def self_ctx():
    return [{"he_ref": "שולחן ערוך, אורח חיים רח:ז", "text": "טקסט"}]


if __name__ == "__main__":
    unittest.main()
