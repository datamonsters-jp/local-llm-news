#!/usr/bin/env python3
"""
update_news.py
毎日 Claude API を呼び出してローカルLLMの最新ニュースを収集し、
news.json を更新するスクリプト。
GitHub Actions から実行されます。
"""

import os
import json
import datetime
import anthropic

# ── 設定 ──────────────────────────────────────────────
MODEL = "claude-opus-4-5"          # 使用モデル
NEWS_JSON = "news.json"            # 出力ファイル
TODAY = datetime.date.today().strftime("%Y.%m.%d")
# ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """
あなたはローカルLLM（オープンウェイトモデル、自己ホスト型LLM）専門のニュースキュレーターです。
最新情報をもとに、日本語でニュースサイト用のJSONデータを生成してください。

必ず以下のJSON形式のみで返してください（マークダウンのコードブロックは不要）:
{
  "updated": "YYYY.MM.DD",
  "ticker": [
    "⚡ ティッカー見出し1（30文字以内）",
    "🟢 ティッカー見出し2",
    "🔥 ティッカー見出し3",
    "💾 ティッカー見出し4",
    "🖥️ ティッカー見出し5"
  ],
  "ranking": [
    {
      "name": "モデル名（例: Qwen3.5-72B）",
      "size": "パラメータ数（例: 72B、109B MoE）",
      "score": 97,
      "country": "国名（例: 中国、米国、仏国）",
      "flag": "国コード: cn/us/fr のいずれか（その他の国は \"\" にする）",
      "org": "開発組織（例: Alibaba、Meta、OpenAI）",
      "reason": "選定理由・特徴（40文字以内）",
      "badges": ["ライセンス", "特徴1", "特徴2"]
    }
  ],
  "featured": {
    "tag": "trend|model|tool|hw|research のいずれか",
    "date": "YYYY.MM.DD",
    "title": "フィーチャー記事タイトル（60文字以内）",
    "summary": "フィーチャー記事の要約（150〜200文字）",
    "url": ""
  },
  "articles": [
    {
      "tag": "trend|model|tool|hw|research のいずれか",
      "date": "YYYY.MM.DD",
      "title": "記事タイトル（50文字以内）",
      "summary": "記事の要約（80〜120文字）",
      "url": "確実に実在する元記事や公式ページのURL。不明な場合は空文字 \"\" にする（架空のURLは絶対に作らない）"
    }
  ]
}

ranking のルール:
- 8件生成すること
- 注目度・性能・話題性の総合スコア（100点満点）で降順に並べる
- 7Bから200B超まで幅広いサイズを含めること（大型モデルも積極的に含める）
- scoreは1位を95〜100、以降は差をつけて設定
- badgesは2〜3個（開発元・ライセンス・用途などの短いラベル）

articles は8〜10件生成してください。
tag は model/tool/hw/research/trend の5種類から選んでください。
"""

USER_PROMPT = f"""
今日は {TODAY} です。
ローカルLLM・オープンウェイトモデルに関する最新ニュースや動向を調査して、
ニュースサイト用のJSONデータを生成してください。

以下の観点でニュースを収集・生成してください：
- 最新のオープンウェイトモデルのリリースや性能情報（Qwen、Llama、Gemma、Mistral、DeepSeekなど）
- Ollama、vLLM、LM Studioなどのランタイム・ツールのアップデート
- GPU・Mac Apple Siliconなどローカル推論向けハードウェア情報
- ベンチマーク・評価結果
- ローカルLLMの活用事例やトレンド

上記のJSON形式のみで返してください。
"""


def fetch_news() -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY が設定されていません")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[{TODAY}] Claude API にニュースを問い合わせ中...")

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_PROMPT}],
    )

    raw = message.content[0].text.strip()

    # コードブロックが混入した場合に除去
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)

    data = json.loads(raw)
    data["updated"] = TODAY  # 日付を確実に上書き
    return data


def save_news(data: dict) -> None:
    with open(NEWS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ {NEWS_JSON} を更新しました（{len(data.get('articles', []))} 件）")


if __name__ == "__main__":
    news_data = fetch_news()
    save_news(news_data)
