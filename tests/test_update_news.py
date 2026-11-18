"""Offline updater regressions. No API SDK, secrets, or network required."""

import copy
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import update_news


def valid_news():
    article = {
        "tag": "model", "date": "2026.10.03", "title": "New open model",
        "summary": "A verified model release.", "url": "https://example.com/news",
    }
    model = {
        "name": "Example model", "size": "1B", "score": 90,
        "released": "2026.10", "country": "日本", "flag": "jp",
        "org": "Example", "reason": "Small local model",
        "badges": ["Open weights"], "url": "https://example.com/model",
    }
    return {
        "updated": "2026.10.04", "ticker": ["New local model"],
        **{key: [copy.deepcopy(model)] for key in update_news.RANKING_KEYS},
        "featured": copy.deepcopy(article), "articles": [copy.deepcopy(article)],
    }


class ValidateNewsTests(unittest.TestCase):
    def test_accepts_current_schema(self):
        data = valid_news()
        self.assertEqual(update_news.validate_news(data), data)

    def test_returns_deep_copy_sorted_without_dropping_any_article(self):
        data = valid_news()
        for date, title in [
            ("2026.09.30", "old"), ("2026.10.04", "new first"),
            ("2026.10.04", "new second"), ("2026.10.03", "duplicate date and URL"),
        ]:
            data["articles"].append({**data["articles"][0], "date": date, "title": title})
        original = copy.deepcopy(data)
        result = update_news.validate_news(data)
        self.assertEqual([a["title"] for a in result["articles"]], [
            "new first", "new second", "New open model", "duplicate date and URL", "old",
        ])
        self.assertEqual(len(result["articles"]), len(data["articles"]))
        self.assertEqual(data, original)
        result["articles"][0]["title"] = "Changed copy"
        result["ranking_general"][0]["badges"].append("Changed copy")
        self.assertEqual(data, original)

    def test_root_and_required_sections(self):
        for root in (None, [], "news", 1, True):
            with self.subTest(root=root), self.assertRaises(ValueError):
                update_news.validate_news(root)
        for field in valid_news():
            data = valid_news()
            del data[field]
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, field):
                update_news.validate_news(data)

    def test_array_sections_must_be_nonempty_arrays(self):
        for key in ("ticker", "articles"):
            for value in (None, {}, "not an array", [], True):
                data = valid_news()
                data[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                    update_news.validate_news(data)

    def test_ranking_arrays_may_be_empty_but_must_be_arrays(self):
        for key in update_news.RANKING_KEYS:
            data = valid_news()
            data[key] = []
            self.assertEqual(update_news.validate_news(data)[key], [])
            for value in (None, {}, "not an array", True):
                data[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                    update_news.validate_news(data)

    def test_ticker_must_contain_nonempty_strings(self):
        for value in (None, {}, 1, True, "", " \n "):
            data = valid_news()
            data["ticker"] = [value]
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "ticker"):
                update_news.validate_news(data)

    def test_article_and_featured_must_be_objects(self):
        for section in ("featured", "articles"):
            for value in (None, [], "article", True):
                data = valid_news()
                data[section] = [value] if section == "articles" else value
                with self.subTest(section=section, value=value), self.assertRaisesRegex(ValueError, section):
                    update_news.validate_news(data)

    def test_article_fields_are_required_nonempty_strings(self):
        for section in ("featured", "articles"):
            for field in ("tag", "date", "title", "summary", "url"):
                for value in (None, 1, True, [], {}, "", "  "):
                    data = valid_news()
                    article = data["featured"] if section == "featured" else data["articles"][0]
                    article[field] = value
                    with self.subTest(section=section, field=field, value=value), self.assertRaisesRegex(ValueError, field):
                        update_news.validate_news(data)
                data = valid_news()
                article = data["featured"] if section == "featured" else data["articles"][0]
                del article[field]
                with self.subTest(section=section, missing=field), self.assertRaisesRegex(ValueError, field):
                    update_news.validate_news(data)

    def test_tag_enum_for_articles_and_featured(self):
        for tag in update_news.ARTICLE_TAGS:
            data = valid_news()
            data["featured"]["tag"] = data["articles"][0]["tag"] = tag
            update_news.validate_news(data)
        for section in ("featured", "articles"):
            data = valid_news()
            article = data["featured"] if section == "featured" else data["articles"][0]
            article["tag"] = "unknown"
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "tag"):
                update_news.validate_news(data)

    def test_dates_must_have_strict_format_and_exist(self):
        for value in ("2026.2.01", "2026-02-01", "2026.02.29", "2026.13.01",
                      "2026.00.01", "2026.01.00", "2026.04.31", "0000.01.01",
                      " 2026.01.01", "2026.01.01\n", "2026.01.01T00:00:00"):
            for field in ("updated", "featured", "articles"):
                data = valid_news()
                if field == "updated":
                    data[field] = value
                elif field == "featured":
                    data[field]["date"] = value
                else:
                    data[field][0]["date"] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    update_news.validate_news(data)

    def test_updated_cannot_be_in_future_in_jst(self):
        data = valid_news()
        tomorrow = datetime.datetime.now(update_news.JST).date() + datetime.timedelta(days=1)
        data["updated"] = tomorrow.strftime("%Y.%m.%d")
        with self.assertRaisesRegex(ValueError, "updated"):
            update_news.validate_news(data)

    def test_updated_uses_jst_calendar_day(self):
        data = valid_news()
        utc_now = datetime.datetime(2026, 10, 3, 16, 0, tzinfo=datetime.timezone.utc)
        with patch.object(update_news.datetime, "datetime", wraps=datetime.datetime) as mocked:
            mocked.now.side_effect = lambda timezone: utc_now.astimezone(timezone)
            update_news.validate_news(data)  # October 4 in JST, October 3 in UTC.
            mocked.now.assert_called_once_with(update_news.JST)

    def test_leap_day_is_valid_and_updated_day_is_allowed(self):
        data = valid_news()
        data["featured"]["date"] = "2024.02.29"
        data["articles"][0]["date"] = data["updated"]
        update_news.validate_news(data)

    def test_article_dates_cannot_exceed_updated(self):
        for field in ("featured", "articles"):
            data = valid_news()
            article = data[field] if field == "featured" else data[field][0]
            article["date"] = "2026.10.05"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "date"):
                update_news.validate_news(data)

    def test_all_ranking_objects_and_fields_are_validated(self):
        model = valid_news()["ranking_general"][0]
        for key in update_news.RANKING_KEYS:
            for value in (None, [], "model", 1):
                data = valid_news()
                data[key] = [value]
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                    update_news.validate_news(data)
            for field in model:
                data = valid_news()
                del data[key][0][field]
                with self.subTest(key=key, missing=field), self.assertRaisesRegex(ValueError, field):
                    update_news.validate_news(data)
            for field in ("name", "size", "released", "country", "org", "reason"):
                for value in (None, 1, True, {}, [], "", "  "):
                    data = valid_news()
                    data[key][0][field] = value
                    with self.subTest(key=key, field=field, value=value), self.assertRaisesRegex(ValueError, field):
                        update_news.validate_news(data)

    def test_scores_must_be_finite_numbers_from_zero_to_one_hundred(self):
        for key in update_news.RANKING_KEYS:
            for value in (None, True, False, "90", [], {}, -0.1, 100.1,
                          float("nan"), float("inf"), float("-inf"), 10**400):
                data = valid_news()
                data[key][0]["score"] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "score"):
                    update_news.validate_news(data)
        for value in (0, 0.5, 99.9, 100):
            data = valid_news()
            data["ranking_general"][0]["score"] = value
            update_news.validate_news(data)

    def test_release_month_must_exist_and_not_exceed_updated_month(self):
        for key in update_news.RANKING_KEYS:
            for value in ("2026.11", "2027.01", "2026.00", "2026.13", "2026.2",
                          "2026-02", "2026.02.01", "0000.01", " 2026.02"):
                data = valid_news()
                data[key][0]["released"] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "released"):
                    update_news.validate_news(data)
        for value in ("2026.10", "2025.12"):
            data = valid_news()
            data["ranking_general"][0]["released"] = value
            update_news.validate_news(data)

    def test_release_format_error_identifies_fifth_item_without_normalizing(self):
        for key in update_news.RANKING_KEYS:
            for value in ("2026", "2026-02", "2026/02", "2026.2", "2026.02.01",
                          " 2026.02", "2026年2月"):
                with self.subTest(key=key, value=value):
                    data = valid_news()
                    data[key] = [copy.deepcopy(data[key][0]) for _ in range(5)]
                    data[key][4]["released"] = value
                    original = copy.deepcopy(data)
                    with self.assertRaises(ValueError) as caught:
                        update_news.validate_news(data)
                    self.assertIn(f"news.{key}[4].released", str(caught.exception))
                    self.assertIn("YYYY.MM", str(caught.exception))
                    self.assertIn(json.dumps(value, ensure_ascii=True), str(caught.exception))
                    self.assertEqual(data, original)

    def test_release_diagnostic_redacts_non_dates_and_is_bounded_single_line(self):
        values = (
            "unused-secret-token", "2026.02 unused-secret-token",
            "2026.02\n::error::injected", "2026.02\x1b[31m",
            "x" * 10000, "2" * 10000, " " * 10000 + "2026.02",
        )
        for value in values:
            with self.subTest(length=len(value)):
                data = valid_news()
                data["ranking_general"][0]["released"] = value
                with self.assertRaises(ValueError) as caught:
                    update_news.validate_news(data)
                error = str(caught.exception)
                self.assertIn("redacted", error)
                self.assertIn(f"length={len(value)}", error)
                self.assertNotIn(value, error)
                self.assertNotIn("unused-secret-token", error)
                self.assertNotIn("::error::", error)
                self.assertNotIn("\n", error)
                self.assertNotIn("\x1b", error)
                self.assertLess(len(error), 180)

    def test_flags_and_badges_are_validated(self):
        for key in update_news.RANKING_KEYS:
            for value in (None, [], True, "gb", "JP", " "):
                data = valid_news()
                data[key][0]["flag"] = value
                with self.subTest(key=key, flag=value), self.assertRaisesRegex(ValueError, "flag"):
                    update_news.validate_news(data)
            for value in (None, {}, "Open", [None], [True], [1], [""], ["  "]):
                data = valid_news()
                data[key][0]["badges"] = value
                with self.subTest(key=key, badges=value), self.assertRaisesRegex(ValueError, "badges"):
                    update_news.validate_news(data)
            data = valid_news()
            data[key][0]["badges"] = []
            self.assertEqual(update_news.validate_news(data)[key][0]["badges"], [])
        for flag in update_news.COUNTRY_FLAGS:
            data = valid_news()
            data["ranking_general"][0]["flag"] = flag
            update_news.validate_news(data)

    def test_all_urls_must_be_absolute_parsed_http_or_https(self):
        for section in ("featured", "articles", *update_news.RANKING_KEYS):
            for url in ("javascript:alert(1)", "data:text/html,test", "ftp://example.com",
                        "//example.com", "/news", "httpjunk", "https://", "https:///news",
                        "https://?q=news", "https://example.com:bad", "https://example.com:99999",
                        "https://[invalid]", " https://example.com", "https://exa mple.com",
                        "https://example.com/\npath", "https://example.com/\x00path",
                        "https://example.com/\x7fpath", "https://example.com\\@evil.example",
                        "https://user:password@example.com"):
                data = valid_news()
                item = data[section] if section == "featured" else data[section][0]
                item["url"] = url
                with self.subTest(section=section, url=url), self.assertRaisesRegex(ValueError, "url"):
                    update_news.validate_news(data)

    def test_valid_urls_and_empty_ranking_url_are_preserved(self):
        for url in ("https://example.com/path?q=local%20llm#news", "http://example.com:8080",
                    "https://[2001:db8::1]/news", "HTTPS://example.com/path"):
            data = valid_news()
            data["featured"]["url"] = url
            result = update_news.validate_news(data)
            self.assertEqual(result["featured"]["url"], url)
        for key in update_news.RANKING_KEYS:
            data = valid_news()
            data[key][0]["url"] = ""
            self.assertEqual(update_news.validate_news(data)[key][0]["url"], "")
            for value in (None, True, 1, [], {}, " "):
                data[key][0]["url"] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "url"):
                    update_news.validate_news(data)


class SaveNewsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "news.json"
        self.original = b'{"existing": "last known good"}\n'
        self.destination.write_bytes(self.original)
        self.destination.chmod(0o644)
        self.patcher = patch.object(update_news, "NEWS_JSON", str(self.destination))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def assert_previous_file_unchanged(self):
        self.assertEqual(self.destination.read_bytes(), self.original)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_invalid_section_aborts_whole_save_and_retains_old_file(self):
        for section in ("updated", "ticker", "featured", "articles", *update_news.RANKING_KEYS):
            data = valid_news()
            data[section] = None
            with self.subTest(section=section), self.assertRaises(ValueError):
                update_news.save_news(data)
            self.assert_previous_file_unchanged()

    def test_invalid_fifth_release_preserves_file_without_writing_temporary(self):
        for key in update_news.RANKING_KEYS:
            data = valid_news()
            data[key] = [copy.deepcopy(data[key][0]) for _ in range(5)]
            data[key][4]["released"] = "2026"
            original = copy.deepcopy(data)
            with self.subTest(key=key), patch.object(
                update_news.tempfile, "NamedTemporaryFile"
            ) as temporary, patch.object(update_news.os, "replace") as replace:
                with self.assertRaises(ValueError) as caught:
                    update_news.save_news(data)
                self.assertIn(f"news.{key}[4].released", str(caught.exception))
                temporary.assert_not_called()
                replace.assert_not_called()
                self.assert_previous_file_unchanged()
                self.assertEqual(data, original)

    def test_direct_save_rejects_future_updated_and_preserves_existing_file(self):
        data = valid_news()
        tomorrow = datetime.datetime.now(update_news.JST).date() + datetime.timedelta(days=1)
        data["updated"] = tomorrow.strftime("%Y.%m.%d")
        data["articles"][0]["date"] = data["updated"]
        with self.assertRaisesRegex(ValueError, "updated"):
            update_news.save_news(data)
        self.assert_previous_file_unchanged()

    def test_one_invalid_article_is_not_silently_dropped(self):
        data = valid_news()
        data["articles"].append({**data["articles"][0], "url": ""})
        with self.assertRaises(ValueError):
            update_news.save_news(data)
        self.assert_previous_file_unchanged()
        self.assertEqual(len(data["articles"]), 2)

    def test_serialization_failure_preserves_old_file(self):
        for value in (float("nan"), object()):
            data = valid_news()
            data["extra"] = value
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                update_news.save_news(data)
            self.assert_previous_file_unchanged()

    def test_atomic_replace_is_same_directory_after_complete_sorted_write(self):
        data = valid_news()
        data["articles"].append({**data["articles"][0], "date": "2026.10.04"})
        expected = update_news.validate_news(data)
        replace = os.replace

        def inspect_replace(source, destination):
            self.assertEqual(Path(source).parent, self.destination.parent)
            self.assertEqual(Path(destination), self.destination)
            self.assertEqual(self.destination.read_bytes(), self.original)
            self.assertEqual(json.loads(Path(source).read_text()), expected)
            replace(source, destination)

        with patch.object(update_news.os, "replace", side_effect=inspect_replace) as mocked:
            update_news.save_news(data)
        mocked.assert_called_once()
        self.assertEqual(json.loads(self.destination.read_text()), expected)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_failed_flush_or_replace_preserves_old_file_and_cleans_temporary(self):
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), patch.object(
                update_news.os, operation, side_effect=OSError("simulated disk failure")
            ), self.assertRaises(OSError):
                update_news.save_news(valid_news())
            self.assert_previous_file_unchanged()

    def test_can_create_first_news_file(self):
        self.destination.unlink()
        update_news.save_news(valid_news())
        self.assertEqual(json.loads(self.destination.read_text()), valid_news())


class FakeLLM:
    """OpenAI互換APIの代わり。プロンプトの種類ごとに決まった応答を返す。"""

    def __init__(self, select, summaries=None, ticker=None):
        self.select, self.summaries, self.ticker = select, summaries or {}, ticker
        self.calls = []

    def json(self, system, user, check=None, max_tokens=0):
        self.calls.append(user)
        if "# 今日の候補記事" in user:
            out = self.select
        elif "ティッカー" in user:
            out = self.ticker or {"ticker": ["⚡ a", "🟢 b", "🔥 c", "💾 d", "🖥️ e"]}
        else:
            title = user.split("タイトル: ", 1)[1].split("\n", 1)[0]
            out = self.summaries.get(title, {"title": "要約: " + title, "summary": "本文に基づく要約です。"})
        if check:
            assert check(out) == [], check(out)
        return out


def candidate(i, date="2026.10.04", **kw):
    row = {"title": f"Model {i} released", "url": f"https://example.org/post-{i}", "source": "example.org",
           "date": date, "snippet": "x" * 100, "excerpt": "本文 " * 40}
    row.update(kw)
    return row


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.object(update_news, "TODAY", "2026.10.04")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def build(self, llm, rows, current=None):
        if current is None:
            current = valid_news()
            current["featured"]["url"] = "https://example.com/featured"
        cands = update_news.dedupe_candidates(rows, current)
        return update_news.build_update(current, llm, cands, fetch=dict)

    def test_adds_selected_articles_with_urls_and_dates_from_candidates(self):
        llm = FakeLLM({"selected": [{"id": "c0", "tag": "tool"}, {"id": "c1", "tag": "model"}], "featured": None})
        data, added = self.build(llm, [candidate(1), candidate(2, date="2026.10.03")])
        self.assertEqual(added, 2)
        urls = [a["url"] for a in data["articles"]]
        self.assertIn("https://example.org/post-1", urls)
        self.assertIn("https://example.org/post-2", urls)
        self.assertEqual(data["updated"], "2026.10.04")
        self.assertEqual(data["ticker"][0], "⚡ a")
        # ランキングは引き継ぐ
        for key in update_news.RANKING_KEYS:
            self.assertEqual(data[key], valid_news()[key])

    def test_featured_replaces_old_featured_which_moves_to_articles(self):
        current = valid_news()
        current["featured"]["url"] = "https://example.com/old-featured"
        llm = FakeLLM({"selected": [{"id": "c0", "tag": "model"}], "featured": "c0"})
        data, added = self.build(llm, [candidate(1)], current)
        self.assertEqual(added, 1)
        self.assertEqual(data["featured"]["url"], "https://example.org/post-1")
        self.assertIn("https://example.com/old-featured", [a["url"] for a in data["articles"]])

    def test_unknown_ids_and_bad_tags_are_ignored(self):
        cands = update_news.dedupe_candidates([candidate(1), candidate(2)], valid_news())
        llm = SimpleNamespace(json=lambda s, u, check=None, max_tokens=0: {
            "selected": [{"id": "c9", "tag": "model"}, {"id": "c1", "tag": "bogus"}, {"id": "c0", "tag": "hw"}],
            "featured": "c9"})
        picked, featured = update_news.step_select(llm, valid_news(), cands)
        self.assertEqual([(p["id"], p["tag"]) for p in picked], [("c0", "hw")])
        self.assertIsNone(featured)

    def test_already_published_and_old_candidates_are_dropped(self):
        rows = [candidate(1, url="https://www.example.com/news/?utm_source=x"),  # 掲載済み（正規化で一致）
                candidate(2, date="2026.09.01"),                                  # 古すぎる
                candidate(3, url="ftp://example.org/x"),                          # http(s)以外
                candidate(4)]
        cands = update_news.dedupe_candidates(rows, valid_news())
        self.assertEqual([c["url"] for c in cands], ["https://example.org/post-4"])

    def test_candidate_without_date_is_skipped(self):
        llm = FakeLLM({"selected": [{"id": "c0", "tag": "model"}], "featured": None})
        data, added = self.build(llm, [candidate(1, date=None)])
        self.assertEqual(added, 0)
        self.assertEqual(data["articles"], valid_news()["articles"])

    def test_llm_skip_and_long_text_is_clipped(self):
        long = {"title": "長" * 80, "summary": "要" * 300}
        llm = FakeLLM({"selected": [{"id": "c0", "tag": "model"}, {"id": "c1", "tag": "tool"}], "featured": None},
                      summaries={"Model 1 released": {"skip": True}, "Model 2 released": long})
        # check() は長すぎるタイトルを指摘するので、ここでは check を通さず確認する
        llm.json = lambda s, u, check=None, max_tokens=0: (
            llm.select if "# 今日の候補記事" in u else
            {"ticker": ["⚡ a", "🟢 b", "🔥 c"]} if "ティッカー" in u else
            llm.summaries[u.split("タイトル: ", 1)[1].split("\n", 1)[0]])
        data, added = self.build(llm, [candidate(1), candidate(2)])
        self.assertEqual(added, 1)
        item = [a for a in data["articles"] if a["url"].endswith("post-2")][0]
        self.assertLessEqual(len(item["title"]), update_news.LIMITS["title"])
        self.assertLessEqual(len(item["summary"]), update_news.LIMITS["summary"])

    def test_articles_are_capped_and_sorted(self):
        current = valid_news()
        current["articles"] = [dict(current["articles"][0], url=f"https://example.com/{i}", date="2026.09.30")
                               for i in range(update_news.ARTICLES_KEEP)]
        llm = FakeLLM({"selected": [{"id": "c0", "tag": "model"}], "featured": None})
        data, _ = self.build(llm, [candidate(1)], current)
        self.assertEqual(len(data["articles"]), update_news.ARTICLES_KEEP)
        self.assertEqual(data["articles"][0]["url"], "https://example.org/post-1")

    def test_parse_feed_reads_rss_and_atom(self):
        rss = b"""<rss><channel><item><title>Hello</title><link>https://a.example/1</link>
        <pubDate>Fri, 03 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Body&lt;/p&gt;</description></item></channel></rss>"""
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v0.41.0</title>
        <link rel="alternate" href="https://github.com/ollama/ollama/releases/tag/v0.41.0"/>
        <updated>2026-10-03T01:00:00Z</updated><content>New features</content></entry></feed>"""
        r = update_news.parse_feed(rss, "https://a.example/feed")[0]
        self.assertEqual((r["title"], r["url"], r["date"], r["snippet"]), ("Hello", "https://a.example/1", "2026.10.03", "Body"))
        g = update_news.parse_feed(atom, "https://github.com/ollama/ollama/releases.atom")[0]
        self.assertEqual(g["title"], "ollama v0.41.0")
        self.assertEqual(g["date"], "2026.10.03")

    def test_missing_llm_settings_fail_clearly(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EnvironmentError, "LLM_BASE_URL"):
                update_news.LLM()

    def test_extract_json_handles_code_fences(self):
        self.assertEqual(update_news.extract_json('```json\n{"a": 1}\n```'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
