#!/usr/bin/env python3
"""
update_news.py
毎日 Claude API + Web検索 でローカルLLMの最新ニュースを収集し、
news.json を更新するスクリプト。GitHub Actions から実行されます。

重要: Web検索ツールを使い、実際に見つかったニュースのみを掲載します。
URLのない記事（=検索で確認できなかった記事）は自動的に除外されます。
"""

import os
import json
import datetime
import anthropic

# ── 設定 ──────────────────────────────────────────────
MODEL = "claude-opus-4-5"
NEWS_JSON = "news.json"
MAX_SEARCHES = 8           # 1回の更新で使うWeb検索の上限
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
ranking_coding はコーディング用途（SWE-bench / LiveCodeBench / コード生成性能を重視）のトップ8を作ること。
両方のランキングで、各モデルの released（リリース年月）は検索で確認した実際の時期を入れること。
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


def fetch_news() -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY が設定されていません")

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

    data = extract_json(full_text)
    data["updated"] = TODAY  # 日付を確実に上書き

    # URLのない記事を除外（捏造防止の最終フィルター）
    before = len(data.get("articles", []))
    data["articles"] = [
        a for a in data.get("articles", [])
        if isinstance(a.get("url"), str) and a["url"].startswith("http")
    ]
    dropped = before - len(data["articles"])
    if dropped:
        print(f"⚠️ URLなしの記事 {dropped} 件を除外しました")

    if not data["articles"]:
        raise ValueError("URL付きの記事が0件でした。news.json は更新しません")

    return data


def save_news(data: dict) -> None:
    with open(NEWS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {NEWS_JSON} を更新しました（記事 {len(data['articles'])} 件、全てURL付き）")


if __name__ == "__main__":
    news_data = fetch_news()
    save_news(news_data)
