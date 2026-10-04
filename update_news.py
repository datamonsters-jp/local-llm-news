#!/usr/bin/env python3
"""
update_news.py
毎日 Claude API + Web検索 でローカルLLMの最新ニュースを収集し、
news.json を更新するスクリプト。GitHub Actions から実行されます。

重要: Web検索ツールを使い、実際に見つかったニュースのみを掲載します。
不正なデータが1件でもある場合は更新を中止し、既存の news.json を保持します。
"""

import os
import json
import datetime
import copy
import math
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

# ── 設定 ──────────────────────────────────────────────
MODEL = "claude-opus-4-5"
NEWS_JSON = "news.json"
MAX_SEARCHES = 4           # 1回の更新で使うWeb検索の上限
JST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(JST).strftime("%Y.%m.%d")  # 日本時間で日付を取得
# ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """
あなたはローカルLLM（オープンウェイトモデル、自己ホスト型LLM）専門のニュースキュレーターです。

【最重要ルール — 必ず守ること】
1. 必ずWeb検索ツールを使って実際のニュースを調べること。記憶や推測でニュースを創作することは絶対に禁止。
2. すべての記事に、検索結果で実際に確認したURLを付けること。URLが確認できないニュースは掲載しない。
3. 日付は記事の実際の公開日を使うこと。存在しない発表や架空の製品（例: 存在しないチップやモデル）を書かない。
4. 海外（英語圏など）のニュースソースを積極的に使い、内容は日本語で要約すること。多様な視点を歓迎する。
5. ランキングも検索で得た最新情報（ベンチマーク、リリース状況）に基づいて作ること。

調査した上で、以下のJSON形式のみで返してください（最後にJSONだけを出力、コードブロック不要）:
{
  "updated": "YYYY.MM.DD",
  "ticker": [
    "⚡ ティッカー見出し1（30文字以内）",
    "🟢 ティッカー見出し2",
    "🔥 ティッカー見出し3",
    "💾 ティッカー見出し4",
    "🖥️ ティッカー見出し5"
  ],
  "ranking_general": [
    {
      "name": "モデル名（例: Qwen3.5-72B）",
      "size": "パラメータ数（例: 72B、109B MoE）",
      "score": 97,
      "released": "リリース年月（例: 2026.02。検索で確認した実際のリリース時期）",
      "country": "国名（例: 中国、米国、仏国）",
      "flag": "国コード: cn/us/fr のいずれか（その他の国は \\"\\" にする）",
      "org": "開発組織（例: Alibaba、Meta、OpenAI）",
      "reason": "選定理由・特徴（40文字以内）",
      "badges": ["ライセンス", "特徴1", "特徴2"],
      "url": "モデルの公式ページURL（HuggingFace・GitHub・公式ブログなど。検索で確認した実在URLのみ。不明なら \\"\\"）"
    }
  ],
  "ranking_coding": [
    {
      "name": "モデル名",
      "size": "パラメータ数",
      "score": 96,
      "released": "リリース年月",
      "country": "国名",
      "flag": "cn/us/fr または \\"\\"",
      "org": "開発組織",
      "reason": "コーディング性能の観点での評価（40文字以内。SWE-bench等の数値があれば含める）",
      "badges": ["ライセンス", "特徴1", "特徴2"],
      "url": "公式ページURL（実在のみ。不明なら \\"\\"）"
    }
  ],
  "ranking_japanese": [
    {
      "name": "モデル名（例: Qwen3 Swallow 32B、Llama 3.3 Swallow 70B など）",
      "size": "パラメータ数",
      "score": 95,
      "released": "リリース年月",
      "country": "国名（日本のモデルは \\"日本\\"）",
      "flag": "国コード。日本は \\"jp\\"、その他は cn/us/fr または \\"\\"",
      "org": "開発組織（例: 東京科学大・産総研、ELYZA、SB Intuitions など）",
      "reason": "日本語性能の観点での評価（40文字以内。日本語MT-Bench等の数値があれば含める）",
      "badges": ["ライセンス", "特徴1", "特徴2"],
      "url": "公式ページURL（HuggingFace等。実在のみ。不明なら \\"\\"）"
    }
  ],
  "ranking_edge": [
    {
      "name": "モデル名（例: Gemma 3n、Qwen3 0.6B、Llama 3.2 1B など）",
      "size": "パラメータ数（例: 0.6B、1B、2B など小型中心）",
      "score": 94,
      "released": "リリース年月",
      "country": "国名",
      "flag": "国コード: cn/us/fr/jp または \\"\\"",
      "org": "開発組織",
      "reason": "エッジ動作の観点での評価（40文字以内。RAM要件・トークン/秒・対応デバイス等）",
      "badges": ["ライセンス", "省メモリ", "特徴"],
      "url": "公式ページURL（実在のみ。不明なら \\"\\"）"
    }
  ],
  "featured": {
    "tag": "trend|model|tool|hw|research のいずれか",
    "date": "YYYY.MM.DD（実際の公開日）",
    "title": "フィーチャー記事タイトル（60文字以内）",
    "summary": "フィーチャー記事の要約（150〜200文字）",
    "url": "検索で確認した実在URL（必須）"
  },
  "articles": [
    {
      "tag": "trend|model|tool|hw|research のいずれか",
      "date": "YYYY.MM.DD（実際の公開日）",
      "title": "記事タイトル（50文字以内）",
      "summary": "記事の要約（80〜120文字）",
      "url": "検索で確認した実在URL（必須。URLがない記事は含めない）"
    }
  ]
}

ranking_general は通常用途（総合力・汎用性能・話題性）のトップ8、
ranking_coding はコーディング用途（SWE-bench / LiveCodeBench / コード生成性能を重視）のトップ8、
ranking_japanese は日本語用途（日本語タスク性能・日本語MT-Bench・日本語知識を重視）のトップ8、
ranking_edge はエッジAI用途（Raspberry Pi・スマホ・組み込み機器など低リソース環境で動く超軽量モデル）のトップ8を作ること。
ranking_edge では、Gemma 3n、Qwen3 0.6B/1.7B、Llama 3.2 1B/3B、Phi-4-mini、SmolLM、TinyLlama、
MobileLLM、BitNet系（1bit LLM）など、おおむね4B以下でメモリ数GB以内・CPU/NPUで動くモデルを中心に選ぶこと。
reasonにはRAM要件やトークン/秒、対応デバイス（ラズパイ・スマホ等）を含めると良い。
ranking_japanese では、東京科学大・産総研のSwallowシリーズ（GPT-OSS Swallow、Qwen3 Swallow、Llama 3.x Swallowなど）、
ELYZA、SB Intuitions（Sarashina）、PLaMo（Preferred Networks）、cyberagent（calm）、Tanuki、rinna、
GENIAC/国のGenAIプロジェクト関連の国産モデルなどを積極的に調べて含めること。
ただし海外モデルでも日本語性能が高ければ含めてよい（Qwen系など）。
すべて検索で実在を確認し、released（リリース年月）も実際の時期を入れること。
articles は見つかった実在ニュースの数だけ（最大10件、最低4件を目標）。
tag は model/tool/hw/research/trend の5種類から選ぶこと。
"""

USER_PROMPT = f"""
今日は {TODAY} です。
Web検索を使って、ローカルLLM・オープンウェイトモデルに関する直近1〜2週間の実際のニュースを調査し、
ニュースサイト用のJSONデータを生成してください。

検索の観点（例）:
- 新しいオープンウェイトモデルのリリース（Qwen、Llama、Gemma、Mistral、DeepSeek、gpt-ossなど）
- Ollama、vLLM、llama.cpp、LM Studioなどのランタイムのアップデート
- ローカル推論向けハードウェア（GPU、Apple Siliconなど）の実際の製品ニュース
- ベンチマーク結果や検証記事
- 海外の技術ブログ・ニュースサイトの記事も積極的に（日本語で要約）

繰り返しますが、検索で実際に確認できたニュースだけを、実在のURLとともに掲載してください。
最後に指定のJSONのみを出力してください。
"""


def extract_json(text: str) -> dict:
    """応答テキストから最初の { と最後の } の間をJSONとして抽出"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSONが見つかりませんでした")
    return json.loads(text[start:end + 1])


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
                raise ValueError(f"{path}.released: YYYY.MM 形式が必要です")
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


def fetch_news() -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY が設定されていません")

    # Import only for real fetches; validation/tests run without the API SDK.
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[{TODAY}] Web検索付きでニュースを収集中...")

    message = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": MAX_SEARCHES,
        }],
    )

    # 検索使用時は複数ブロックで返るため、textブロックを全て連結
    full_text = "".join(
        block.text for block in message.content if block.type == "text"
    )

    data = validate_news(extract_json(full_text))
    data["updated"] = TODAY  # 日本時間の実行日を設定し、その日付でも再検証
    return validate_news(data)


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


if __name__ == "__main__":
    news_data = fetch_news()
    save_news(news_data)

