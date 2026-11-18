#!/usr/bin/env python3
"""
update_news.py — LOCAL LLM NEWS の毎朝の自動更新（ローカルLLM版）

ニュース検索は Python 側で行い（DuckDuckGo News / SearXNG / RSS・Atom）、
LLM には「選定・要約・ティッカーづくり」だけを任せます。
LLM は OpenAI 互換 API（vLLM / SGLang / llama.cpp / Ollama など）で呼ぶので、
DGX Spark の GLM などローカルLLMでそのまま動きます。

URL と日付は検索結果・記事ページからプログラムが埋めるため、LLM が創作する余地はありません。
ランキング（ranking_*）は自動では書き換えず、既存の内容をそのまま引き継ぎます。
不正なデータが1件でもあれば保存を中止し、既存の news.json を保持します。

必要な環境変数（scripts/.env に書けば自動で読み込みます）:
  LLM_BASE_URL   : OpenAI互換APIのベースURL（例: http://spark-1:8000/v1）
  LLM_MODEL      : モデル名（サーバー側の served model name）
任意:
  LLM_API_KEY    : APIキー
  LLM_JSON_MODE  : 1 なら response_format=json_object を送る（既定: 1）
  LLM_EXTRA_BODY : リクエストに混ぜるJSON（例: {"chat_template_kwargs":{"enable_thinking":false}}）
  LLM_TIMEOUT    : 1リクエストのタイムアウト秒（既定: 900）
  SEARCH_BACKEND : ddgs（既定） / searxng / none（RSSのみ）
  SEARXNG_URL    : SEARCH_BACKEND=searxng のときの SearXNG のURL

使い方:
  python3 update_news.py              # 通常実行（news.json を更新）
  python3 update_news.py --dry-run    # 書き込まずに結果を表示
  python3 update_news.py --candidates-file c.json  # 検索の代わりに候補JSONを使う（テスト用）
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import copy
import datetime
import email.utils
import html
import json
import math
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

# ── 設定 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
NEWS_JSON = str(ROOT / "news.json")
JST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(JST).strftime("%Y.%m.%d")  # 日本時間で日付を取得

LOOKBACK_DAYS = 10        # これより古い候補は捨てる
MAX_CANDIDATES = 50       # LLMに見せる候補の上限
MAX_NEW_ITEMS = 6         # 1日に追加する記事の上限
ARTICLES_KEEP = 10        # articles に残す件数
EXCERPT_CHARS = 2500      # 要約時にLLMへ渡す本文の長さ
UA = "Mozilla/5.0 (compatible; LocalLLMNewsBot/2.0; +https://datamonsters-jp.github.io/local-llm-news/)"

LIMITS = {"ticker": 30, "title": 50, "summary": 130, "featured.title": 60, "featured.summary": 210}

SEARCH_QUERIES = [
    # (クエリ, ddgsのregion)
    ("open-weight model release", "us-en"),
    ("open source LLM release Hugging Face", "us-en"),
    ("local LLM", "us-en"),
    ("Ollama", "us-en"),
    ("llama.cpp OR vLLM OR \"LM Studio\"", "us-en"),
    ("Qwen OR DeepSeek OR GLM open weights", "us-en"),
    ("Gemma OR Llama OR Mistral open model", "us-en"),
    ("ローカルLLM", "jp-jp"),
    ("オープンウェイト モデル 公開", "jp-jp"),
    ("日本語 LLM 公開 Swallow OR Sarashina OR PLaMo OR ELYZA", "jp-jp"),
]

FEEDS = [
    "https://huggingface.co/blog/feed.xml",
    "https://github.com/ollama/ollama/releases.atom",
    "https://github.com/vllm-project/vllm/releases.atom",
    "https://lmstudio.ai/rss.xml",
]
# ──────────────────────────────────────────────────────

RANKING_KEYS = (
    "ranking_general", "ranking_coding", "ranking_japanese", "ranking_edge",
)
ARTICLE_TAGS = {"trend", "model", "tool", "hw", "research"}
COUNTRY_FLAGS = {"", "cn", "us", "fr", "jp"}


def _required(obj: dict, key: str, path: str):
    if key not in obj:
        raise ValueError(f"{path}.{key}: 必須項目がありません")
    return obj[key]


def _string(value, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{path}: 文字列が必要です（空文字不可）")
    return value


def _object(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: オブジェクトが必要です")
    return value


def _array(value, path: str, *, nonempty: bool = True) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        requirement = "空でない配列" if nonempty else "配列"
        raise ValueError(f"{path}: {requirement}が必要です")
    return value


def _date(value, path: str) -> datetime.date:
    _string(value, path)
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}", value):
        raise ValueError(f"{path}: 日付は YYYY.MM.DD 形式で指定してください")
    try:
        return datetime.date.fromisoformat(value.replace(".", "-"))
    except ValueError as exc:
        raise ValueError(f"{path}: 実在する日付が必要です") from exc


def _url(value, path: str, *, allow_empty: bool = False) -> None:
    _string(value, path, allow_empty=allow_empty)
    if allow_empty and value == "":
        return
    # urlsplit strips some control characters; reject them before parsing.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError(f"{path}: URLに空白・制御文字・バックスラッシュは使えません")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.netloc)
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
        # Accessing port also rejects malformed/out-of-range port values.
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{path}: 不正なURLです") from exc
    if not valid:
        raise ValueError(f"{path}: 絶対URL（http/https）が必要です")


def _article(value, path: str, updated: datetime.date) -> None:
    article = _object(value, path)
    for key in ("tag", "date", "title", "summary", "url"):
        _string(_required(article, key, path), f"{path}.{key}")
    if article["tag"] not in ARTICLE_TAGS:
        raise ValueError(f"{path}.tag: 不正な記事カテゴリです")
    if _date(article["date"], f"{path}.date") > updated:
        raise ValueError(f"{path}.date: 更新日より未来の記事は掲載できません")
    _url(article["url"], f"{path}.url")


def _released_diagnostic(value: str) -> str:
    """Show only short date-shaped values; never echo arbitrary model output."""
    # Keep diagnostics single-line and bounded. Unexpected text could contain
    # credentials or log-control syntax, so disclose its length, not its text.
    if len(value) <= 32 and re.fullmatch(
        r" *[0-9]{4}(?:(?:[./-][0-9]{1,2}){0,2}|年[0-9]{1,2}月(?:[0-9]{1,2}日)?) *",
        value,
    ):
        return json.dumps(value, ensure_ascii=True)
    return f"<redacted non-date value; length={len(value)}>"


def validate_news(data: dict) -> dict:
    """Validate the entire payload and return a newest-first copy.

    No entries are dropped or modified in place. A single invalid section aborts
    the update, so callers can safely retain the last successful news.json.
    """
    data = _object(data, "news")
    updated = _date(_required(data, "updated", "news"), "news.updated")
    if updated > datetime.datetime.now(JST).date():
        raise ValueError("news.updated: 日本時間の現在日より未来の更新日は指定できません")
    ticker = _array(_required(data, "ticker", "news"), "news.ticker")
    for index, headline in enumerate(ticker):
        _string(headline, f"news.ticker[{index}]")

    for key in RANKING_KEYS:
        ranking = _array(_required(data, key, "news"), f"news.{key}", nonempty=False)
        for index, value in enumerate(ranking):
            path = f"news.{key}[{index}]"
            model = _object(value, path)
            for field in ("name", "size", "released", "country", "org", "reason"):
                _string(_required(model, field, path), f"{path}.{field}")
            flag = _string(_required(model, "flag", path), f"{path}.flag", allow_empty=True)
            if flag not in COUNTRY_FLAGS:
                raise ValueError(f"{path}.flag: 不正な国コードです")
            score = _required(model, "score", path)
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not 0 <= score <= 100 or not math.isfinite(score)):
                raise ValueError(f"{path}.score: 0〜100の有限数が必要です")
            released = model["released"]
            if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}", released):
                raise ValueError(
                    f"{path}.released: YYYY.MM 形式が必要です"
                    f" (received={_released_diagnostic(released)})"
                )
            released_date = _date(released + ".01", f"{path}.released")
            if (released_date.year, released_date.month) > (updated.year, updated.month):
                raise ValueError(f"{path}.released: 更新月より未来のモデルは掲載できません")
            badges = _array(_required(model, "badges", path), f"{path}.badges", nonempty=False)
            for badge_index, badge in enumerate(badges):
                _string(badge, f"{path}.badges[{badge_index}]")
            _url(_required(model, "url", path), f"{path}.url", allow_empty=True)

    _article(_required(data, "featured", "news"), "news.featured", updated)
    articles = _array(_required(data, "articles", "news"), "news.articles")
    for index, article in enumerate(articles):
        _article(article, f"news.articles[{index}]", updated)

    validated = copy.deepcopy(data)
    # The fixed-width date format above is chronologically sortable. Sorting is
    # stable so same-day articles keep their source order, including duplicates.
    validated["articles"].sort(key=lambda article: article["date"], reverse=True)
    return validated




# ---------------------------------------------------------------------------
# 小物
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def http_get(url: str, timeout: int = 15, max_bytes: int = 2_000_000) -> tuple[bytes, str]:
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")  # 日本語URL対策
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes), r.headers.get("Content-Type", "")


def decode_html(raw: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4000], re.I)
        enc = m.group(1).decode() if m else "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def parse_date(value) -> str | None:
    """いろいろな日付表記を 'YYYY.MM.DD'（JST）にする。"""
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", s):
        return s
    dt = None
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(s)
        except (TypeError, ValueError):
            m = re.search(r"(20\d\d)[./年-](\d{1,2})[./月-](\d{1,2})", s)
            if m:
                try:
                    dt = datetime.datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=JST)
                except ValueError:
                    return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(JST).strftime("%Y.%m.%d")


def is_recent(date_str: str | None) -> bool:
    if not date_str:
        return True  # 日付不明は一旦残し、記事ページの日付で判断する
    try:
        d = datetime.datetime.strptime(date_str, "%Y.%m.%d").date()
    except ValueError:
        return True
    today = datetime.datetime.strptime(TODAY, "%Y.%m.%d").date()
    return today - datetime.timedelta(days=LOOKBACK_DAYS) <= d <= today


def norm_url(url: str) -> str:
    """重複判定用にURLを正規化（追跡パラメータ・末尾スラッシュ・www を落とす）。"""
    p = urllib.parse.urlsplit(url.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ocid"))]
    host = re.sub(r"^www\.", "", p.netloc.lower())
    return urllib.parse.urlunsplit(("https", host, p.path.rstrip("/"), urllib.parse.urlencode(q), ""))


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def clip(text: str, lim: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= lim:
        return text
    cut = text[: lim - 1]
    for sep in ("。", "、", " "):
        i = cut.rfind(sep)
        if i >= lim * 0.6:
            return cut[: i + (1 if sep == "。" else 0)].rstrip("、 ") + ("" if sep == "。" else "…")
    return cut + "…"


# ---------------------------------------------------------------------------
# 候補収集
# ---------------------------------------------------------------------------
def search_ddgs() -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        log("  ddgs が未インストールです（pip install ddgs）。検索をスキップします。")
        return []
    out = []
    with DDGS() as ddg:
        for q, region in SEARCH_QUERIES:
            try:
                rows = ddg.news(q, region=region, timelimit="w", max_results=10) or []
            except Exception as e:  # レート制限などは他のクエリで補う
                log(f"  検索失敗「{q}」: {e}")
                continue
            for r in rows:
                out.append({
                    "title": r.get("title", ""), "url": r.get("url", ""),
                    "source": r.get("source", ""), "date": parse_date(r.get("date")),
                    "snippet": r.get("body", ""), "query": q,
                })
    return out


def search_searxng() -> list[dict]:
    base = os.environ.get("SEARXNG_URL", "").rstrip("/")
    if not base:
        log("  SEARXNG_URL が未設定です。検索をスキップします。")
        return []
    out = []
    for q, region in SEARCH_QUERIES:
        lang = "ja" if region.startswith("jp") else "en"
        url = f"{base}/search?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "categories": "news", "time_range": "week", "language": lang}
        )
        try:
            raw, _ = http_get(url, timeout=30)
            rows = json.loads(raw).get("results", [])[:10]
        except Exception as e:
            log(f"  検索失敗「{q}」: {e}")
            continue
        for r in rows:
            out.append({
                "title": r.get("title", ""), "url": r.get("url", ""),
                "source": urllib.parse.urlsplit(r.get("url", "")).netloc,
                "date": parse_date(r.get("publishedDate")),
                "snippet": r.get("content", ""), "query": q,
            })
    return out


ATOM = "{http://www.w3.org/2005/Atom}"


def parse_feed(raw: bytes, feed_url: str) -> list[dict]:
    """RSS 2.0 と Atom の両方を読む。"""
    root = ET.fromstring(raw)
    host = urllib.parse.urlsplit(feed_url).netloc
    prefix = ""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/releases", feed_url)
    if m:  # GitHubのリリースはタイトルがバージョン番号だけなので、リポジトリ名を付ける
        prefix = m.group(1).split("/")[1] + " "
        host = "github.com/" + m.group(1)
    out = []
    for item in root.iter("item"):
        out.append({
            "title": prefix + strip_tags(item.findtext("title", "")),
            "url": (item.findtext("link") or "").strip(),
            "source": host, "date": parse_date(item.findtext("pubDate")),
            "snippet": strip_tags(item.findtext("description", ""))[:400], "query": "feed",
        })
    for entry in root.iter(ATOM + "entry"):
        link = ""
        for ln in entry.findall(ATOM + "link"):
            if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                link = ln.get("href")
                break
        body = entry.findtext(ATOM + "summary") or entry.findtext(ATOM + "content") or ""
        out.append({
            "title": prefix + strip_tags(entry.findtext(ATOM + "title", "")),
            "url": link.strip(), "source": host,
            "date": parse_date(entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated")),
            "snippet": strip_tags(body)[:400], "query": "feed",
        })
    return out


def fetch_feeds() -> list[dict]:
    out = []
    for feed in FEEDS:
        try:
            raw, _ = http_get(feed, timeout=20)
            out += parse_feed(raw, feed)
        except Exception as e:
            log(f"  フィード取得失敗 {feed}: {e}")
    return out


def collect_candidates(current: dict) -> list[dict]:
    backend = os.environ.get("SEARCH_BACKEND", "ddgs").lower()
    rows = []
    if backend == "ddgs":
        rows += search_ddgs()
    elif backend == "searxng":
        rows += search_searxng()
    rows += fetch_feeds()
    return dedupe_candidates(rows, current)


def published_items(current: dict) -> list[dict]:
    return list(current.get("articles", [])) + ([current["featured"]] if current.get("featured") else [])


def dedupe_candidates(rows: list[dict], current: dict) -> list[dict]:
    published = published_items(current)
    seen = {norm_url(a["url"]) for a in published}
    seen_titles = {re.sub(r"\W", "", a["title"])[:30] for a in published}
    out = []
    for r in rows:
        url = (r.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = norm_url(url)
        tkey = re.sub(r"\W", "", r.get("title", ""))[:30]
        if key in seen or (tkey and tkey in seen_titles):
            continue
        r = dict(r, url=url, date=parse_date(r.get("date")))
        if not is_recent(r["date"]):
            continue
        seen.add(key)
        seen_titles.add(tkey)
        out.append(r)
    out.sort(key=lambda r: r.get("date") or "", reverse=True)
    out = out[:MAX_CANDIDATES]
    for i, r in enumerate(out):
        r["id"] = f"c{i}"
    return out


# ---------------------------------------------------------------------------
# 記事本文の取得（LLMが要約の根拠にする）
# ---------------------------------------------------------------------------
class _ArticleParser(HTMLParser):
    SKIP = ("script", "style", "nav", "footer", "header", "aside")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.paras = {}, []
        self._in_p = self._skip = 0
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"])
        elif tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "li") and not self._skip:
            self._in_p += 1
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in ("p", "li") and self._in_p:
            self._in_p -= 1
            t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(t) >= 25:
                self.paras.append(t)

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


def fetch_article(c: dict) -> dict:
    """本文抜粋と公開日を取得して候補に足す。失敗したらスニペットだけで続行。"""
    c = dict(c)
    try:
        raw, ctype = http_get(c["url"], timeout=15)
        p = _ArticleParser()
        p.feed(decode_html(raw, ctype))
        desc = p.meta.get("og:description") or p.meta.get("description") or ""
        c["excerpt"] = (desc + "\n" + " ".join(p.paras)).strip()[:EXCERPT_CHARS]
        c["date"] = c.get("date") or parse_date(
            p.meta.get("article:published_time") or p.meta.get("og:published_time")
            or p.meta.get("datepublished") or p.meta.get("date")
        )
    except Exception as e:
        log(f"  本文取得失敗 {c['url'][:80]}: {e}")
        c.setdefault("excerpt", "")
    return c


# ---------------------------------------------------------------------------
# LLM（OpenAI互換API）
# ---------------------------------------------------------------------------
class LLM:
    def __init__(self):
        self.base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "")
        self.key = os.environ.get("LLM_API_KEY", "")
        self.json_mode = os.environ.get("LLM_JSON_MODE", "1") == "1"
        self.timeout = int(os.environ.get("LLM_TIMEOUT", "900"))
        self.extra = json.loads(os.environ.get("LLM_EXTRA_BODY") or "{}")
        if not self.base or not self.model:
            raise EnvironmentError("LLM_BASE_URL と LLM_MODEL を設定してください（scripts/.env）")

    def chat(self, messages: list[dict], max_tokens: int = 4000) -> str:
        body = {"model": self.model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(self.extra)
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(
            self.base + "/chat/completions", data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            resp = json.loads(r.read())
        text = resp["choices"][0]["message"].get("content") or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def json(self, system: str, user: str, check=None, max_tokens: int = 4000) -> dict:
        """JSONを返させる。壊れていたら、または check() が問題を返したら1回だけ直させる。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last = None
        for attempt in range(2):
            text = self.chat(messages, max_tokens=max_tokens)
            try:
                data = extract_json(text)
                problems = check(data) if check else []
            except (ValueError, json.JSONDecodeError) as e:
                data, problems = None, [f"JSONとして読めません: {e}"]
            if not problems:
                return data
            last = (data, problems)
            log("    出力に問題 → 書き直しを依頼" if attempt == 0 else f"    問題が残りました: {problems[:3]}")
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "次の問題を直して、JSONのみで出力し直してください。\n- " + "\n- ".join(problems[:30])},
            ]
        if last and last[0] is not None:
            return last[0]  # 文字数超過などは後段で切り詰める
        raise ValueError(f"LLMから有効なJSONを得られませんでした: {last[1] if last else ''}")


def extract_json(text: str) -> dict:
    """応答テキストから最初の { と最後の } の間をJSONとして抽出"""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("JSONが見つかりませんでした")
    return json.loads(text[start:end + 1])


SYSTEM = (
    "あなたは「LOCAL LLM NEWS」— ローカルLLM（オープンウェイトモデル、自己ホスト型LLM）専門ニュースサイトの編集者です。"
    "与えられた資料だけを根拠に日本語で書き、数字・固有名詞・日付・製品名を創作しません。"
    "MoEの総パラメータとアクティブ数を混同しない。Ollamaのcloud版やAPI限定のモデルをローカル配布と扱わない。"
    "重みが未公開なら公開待ちと明記する。PCの構成例・必要メモリ・推論速度の保証は書かない。"
    "出力は必ず指定されたJSONのみ。説明文やコードフェンスは付けません。"
)


# ---- ステップ1: 候補から採用記事を選ぶ --------------------------------------
def step_select(llm: LLM, current: dict, cands: list[dict]) -> tuple[list[dict], str | None]:
    existing = "\n".join(f"- {a['date']} {a['title']}" for a in published_items(current))
    lines = "\n".join(
        f"[{c['id']}] {c.get('date') or '日付不明'} | {c.get('source', '')} | {c['title']}\n"
        f"    {strip_tags(c.get('snippet', ''))[:220]}"
        for c in cands
    )
    ids = {c["id"] for c in cands}

    def check(d):
        sel = d.get("selected")
        if not isinstance(sel, list):
            return ["selected 配列がありません"]
        probs = []
        for s in sel:
            if not isinstance(s, dict) or s.get("id") not in ids:
                probs.append(f"存在しないid: {s.get('id') if isinstance(s, dict) else s}")
            elif s.get("tag") not in ARTICLE_TAGS:
                probs.append(f"tagが不正: {s.get('tag')}")
        f = d.get("featured")
        if f not in (None, "") and f not in {s.get("id") for s in sel if isinstance(s, dict)}:
            probs.append("featured は selected の中のidにしてください")
        return probs

    user = f"""今日の日付（日本時間）: {TODAY}

# サイトに掲載済みの記事（これと同じ話題は選ばない）
{existing}

# 今日の候補記事
{lines}

# タスク
候補から、サイトに新しく載せる価値のあるニュースを最大{MAX_NEW_ITEMS}本選んでください。
- 対象: オープンウェイトモデルの公開、Ollama / llama.cpp / vLLM / LM Studio などローカル推論ツールの更新、
  ローカル推論向けハードウェアの実製品ニュース、ベンチマーク・検証・研究、ローカルLLMの業界動向
- 除外: API・クラウド限定のモデルだけの話題、クラウドの推論API・推論プロバイダの提携や料金の話題（手元で動かす話ではないもの）、広告・セール記事、まとめサイトの再掲、内容の薄い質問投稿
- 細かなパッチリリース（バグ修正だけ等）は選ばない。大きな機能追加のあるリリースは可
- 掲載済みと同じ話題、候補同士で重複する話題は1本にまとめる（一次情報や詳しそうな方を選ぶ）
- 該当がなければ空配列でよい
- tag: model=モデル公開 / tool=ツール・ランタイム / hw=ハードウェア / research=研究・ベンチマーク / trend=業界動向
- featured: 選んだ中で今日いちばん大きなニュースのid（無理に選ばなくてよい。なければ null）

# 出力形式
{{"selected": [{{"id": "c0", "tag": "model"}}], "featured": "c0"}}"""
    data = llm.json(SYSTEM, user, check=check, max_tokens=1500)
    by_id = {c["id"]: c for c in cands}
    out, used = [], set()
    for s in (data.get("selected") or [])[:MAX_NEW_ITEMS]:
        if not isinstance(s, dict):
            continue
        c = by_id.get(s.get("id"))
        if c and c["id"] not in used and s.get("tag") in ARTICLE_TAGS:
            used.add(c["id"])
            out.append(dict(c, tag=s["tag"]))
    featured = data.get("featured") if data.get("featured") in used else None
    return out, featured


# ---- ステップ2: 1本ずつ要約 ------------------------------------------------
def step_summarize(llm: LLM, c: dict, featured: bool = False) -> dict | None:
    if not c.get("date") or not is_recent(c["date"]):
        log(f"  公開日を確認できないため見送り: {c['title'][:50]}")
        return None
    source_text = (c.get("excerpt") or "").strip() or strip_tags(c.get("snippet", ""))
    if len(source_text) < 60:
        log(f"  本文が短すぎるため見送り: {c['title'][:50]}")
        return None
    t_lim = LIMITS["featured.title" if featured else "title"]
    length = "150〜200文字" if featured else "80〜120文字"

    def check(d):
        probs = []
        if d.get("skip"):
            return probs
        for k in ("title", "summary"):
            if not isinstance(d.get(k), str) or not d[k].strip():
                probs.append(f"{k} がありません")
        if isinstance(d.get("title"), str) and len(d["title"]) > t_lim:
            probs.append(f"title を{t_lim}文字以内に（今{len(d['title'])}文字）")
        s_lim = 200 if featured else 120
        if isinstance(d.get("summary"), str) and len(d["summary"]) > s_lim:
            probs.append(f"summary を{s_lim}文字以内に（今{len(d['summary'])}文字）。文の途中で切らず短く書き直す")
        return probs

    user = f"""# 記事
タイトル: {c['title']}
媒体: {c.get('source', '')}
公開日: {c['date']}
本文（抜粋）:
{source_text}

# タスク
この記事をローカルLLMニュースサイト向けに日本語で紹介してください。
- title: {t_lim}文字以内。何が起きたかが一目でわかる見出し（例: 「Ollama 0.40.17リリース: MLX並列生成対応」）
- summary: {length}。本文に書かれている事実だけで。本文に無い数字・日付・性能は書かない
- 本文がローカルLLMと関係ない、または中身が読み取れない場合は {{"skip": true}} だけを返す

# 出力形式
{{"title": "...", "summary": "..."}}"""
    d = llm.json(SYSTEM, user, check=check, max_tokens=1200)
    if d.get("skip"):
        log(f"  LLMが見送り: {c['title'][:50]}")
        return None
    return {
        "tag": c["tag"],
        "date": c["date"],
        "title": clip(d.get("title", ""), t_lim),
        "summary": clip(d.get("summary", ""), LIMITS["featured.summary" if featured else "summary"]),
        "url": c["url"],
    }


# ---- ステップ3: ティッカー --------------------------------------------------
def step_ticker(llm: LLM, data: dict) -> list[str]:
    items = [data["featured"]] + data["articles"][:8]
    lines = "\n".join(f"- {a['date']} [{a['tag']}] {a['title']}: {a['summary']}" for a in items)

    def check(d):
        t = d.get("ticker")
        if not isinstance(t, list) or len(t) != 5 or not all(isinstance(x, str) and x.strip() for x in t):
            return ["ticker は5個の文字列の配列にしてください"]
        return [f"「{x}」を{LIMITS['ticker']}文字以内に" for x in t if len(x) > LIMITS["ticker"]]

    user = f"""# サイトに載っている記事（新しい順）
{lines}

# タスク
サイト上部を流れるティッカーの見出しを5本作ってください。
- 上の記事に書かれた事実だけを使う。新しい記事を優先
- 各{LIMITS['ticker']}文字以内。先頭に絵文字を1つ（⚡ 🟢 🔥 💾 🖥️ など）

# 出力形式
{{"ticker": ["⚡ ...", "🟢 ...", "🔥 ...", "💾 ...", "🖥️ ..."]}}"""
    d = llm.json(SYSTEM, user, check=check, max_tokens=800)
    # 途中で「…」と切れた見出しは見栄えが悪いので、長すぎるものは使わない
    ticker = [x.strip() for x in (d.get("ticker") or [])
              if isinstance(x, str) and x.strip() and len(x.strip()) <= LIMITS["ticker"]]
    if len(ticker) < 3:
        raise ValueError("ティッカーが足りません")
    return ticker[:5]


# ---------------------------------------------------------------------------
# 組み立て
# ---------------------------------------------------------------------------
def merge_articles(data: dict, new_items: list[dict], new_featured: dict | None) -> dict:
    """新しい記事を足して、古いものから落とす。featured を差し替えたら旧featuredは記事一覧へ。"""
    data = copy.deepcopy(data)
    articles = list(new_items) + data["articles"]
    if new_featured:
        articles.append(data["featured"])
        data["featured"] = new_featured
    # 同じURLでも別記事のことがある（まとめ記事など）ので、URL＋タイトルで重複を判定する
    seen, merged = {(norm_url(data["featured"]["url"]), data["featured"]["title"])}, []
    for a in sorted(articles, key=lambda a: a["date"], reverse=True):
        key = (norm_url(a["url"]), a["title"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(a)
    data["articles"] = merged[:ARTICLES_KEEP]
    return data


def build_update(current: dict, llm: LLM, cands: list[dict], fetch=fetch_article) -> tuple[dict, int]:
    """候補からニュースを作り、検証済みの新しい news を返す（ランキングは引き継ぎ）。"""
    new_items, new_featured = [], None
    if cands:
        log("2/4 LLMが採用記事を選定中...")
        picked, featured_id = step_select(llm, current, cands)
        log(f"  採用候補 {len(picked)} 件")
        with futures.ThreadPoolExecutor(max_workers=6) as ex:
            picked = list(ex.map(fetch, picked))
        log("3/4 LLMが1本ずつ要約中...")
        for c in picked:
            is_featured = c["id"] == featured_id
            try:
                item = step_summarize(llm, c, featured=is_featured)
            except Exception as e:
                log(f"  要約失敗（見送り）: {e}")
                item = None
            if not item:
                continue
            if is_featured:
                new_featured = item
            else:
                new_items.append(item)
            log(f"  + [{item['tag']}] {item['title']}{' ★featured' if is_featured else ''}")

    data = merge_articles(current, new_items, new_featured)
    added = len(new_items) + (1 if new_featured else 0)
    if added:
        log("4/4 LLMがティッカーを更新中...")
        try:
            data["ticker"] = step_ticker(llm, data)
        except Exception as e:
            log(f"  ティッカー更新に失敗（前日のまま）: {e}")
    data["updated"] = TODAY
    return validate_news(data), added


def save_news(data: dict) -> None:
    """Validate and serialize before atomically replacing the published file."""
    validated = validate_news(data)
    serialized = json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    destination = Path(NEWS_JSON)
    temporary_path = None
    try:
        # A sibling temporary file guarantees os.replace stays on one filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        if destination.exists():
            os.chmod(temporary_path, destination.stat().st_mode & 0o777)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    print(f"✅ {NEWS_JSON} を更新しました（記事 {len(validated['articles'])} 件、全て検証済み）")




# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def load_env_file(path: Path) -> None:
    """scripts/.env を読み込む（すでに設定済みの環境変数は上書きしない）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv=None) -> int:
    load_env_file(ROOT / "scripts" / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="news.jsonを書き換えずに結果を表示")
    ap.add_argument("--candidates-file", help="検索の代わりに使う候補JSON（テスト用）")
    args = ap.parse_args(argv)

    current = json.loads(Path(NEWS_JSON).read_text(encoding="utf-8"))
    llm = LLM()

    log(f"[{TODAY}] 1/4 ニュース候補を収集中...")
    if args.candidates_file:
        rows = json.loads(Path(args.candidates_file).read_text(encoding="utf-8"))
        cands = dedupe_candidates(rows, current)
        fetch = lambda c: dict(c)  # noqa: E731  テスト時は本文を取りに行かない
    else:
        cands = collect_candidates(current)
        fetch = fetch_article
    log(f"  新しい候補 {len(cands)} 件")

    try:
        data, added = build_update(current, llm, cands, fetch=fetch)
    except ValueError as e:
        log(f"ERROR: 検証に失敗したため更新しません: {e}")
        return 1

    if added == 0:
        print("新しいニュースはありませんでした。news.json は更新しません。")
        return 0
    if args.dry_run:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    save_news(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
