# LOCAL LLM NEWS 🌟

ローカルLLMの最新情報を毎朝自動更新するネオンライト風ニュースサイトです。

## 構成

```
.
├── index.html                      # サイト本体（news.json を読み込んで表示）
├── news.json                       # ニュースデータ（毎日自動更新）
├── update_news.py                  # Claude API でニュースを生成するスクリプト
└── .github/workflows/
    └── update-news.yml             # 毎朝7時(JST)に自動実行
```

## セットアップ手順

### 1. リポジトリを作成

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/local-llm-news.git
git push -u origin main
```

### 2. GitHub Pages を有効化

1. リポジトリの **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** / **/ (root)**
4. **Save**

しばらくすると `https://<ユーザー名>.github.io/local-llm-news/` で公開されます。

### 3. Anthropic API キーを取得

1. [console.anthropic.com](https://console.anthropic.com) にアクセス
2. **API Keys** → **Create Key**
3. キーをコピー（`sk-ant-...` から始まる文字列）

### 4. GitHub Secrets に登録

1. リポジトリの **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**
   - Name: `ANTHROPIC_API_KEY`
   - Secret: コピーしたAPIキー
3. **Add secret**

### 5. 動作確認（手動実行）

1. **Actions** タブ → **Daily News Update**
2. **Run workflow** → **Run workflow**
3. 緑のチェックが付けばOK！`news.json` が更新されます

## 自動更新スケジュール

毎朝 **7:00 JST** に GitHub Actions が自動実行され、Claude API が最新のローカルLLMニュースを生成して `news.json` を更新します。

## コスト目安

Claude API の利用料金は1回の更新あたり **約1〜3円**（月30〜90円程度）です。

## ライセンス

MIT


## オフライン検証

Node.js 20以上とPython 3.10以上で、APIキーなしで検証できます。

```bash
npm ci
npm test
```

DOMテストはjsdomで生成テキストの安全な描画、URL・スキーマ検証、日付順、取得前のタブ選択、取得失敗、再試行、既存データ維持を検証します。PythonテストはAPIをモックし、データ検証と原子的保存を検証します。実際のAPIは呼びません。

任意のブラウザ回帰テストはPlaywrightとChromiumがある環境で `node tests/browser.cjs` を実行できます。システムChromiumを使う場合は `CHROMIUM_PATH` を指定してください。このテストは外部通信を遮断し、ローカルのfixtureで応答します。

### データの扱い

- 生成データはHTMLとして挿入せず、テキストノードと解析済みHTTP(S)リンクとして描画します。
- 新規生成データの必須項目・日付・スコア・URLを検証し、不正なら更新全体を中止します。既存のファイルを切り詰めません。
- 新規モデルのリリース日は `YYYY.MM` 必須です。表示側は既存データの年だけの値もその精度のまま表示し、月を推測しません。
- ニュースは日付の降順に表示し、同日の記事順と全件を維持します。過去の更新分を蓄積する機能は含みません。
- ランキング取得中・失敗時は保存データを維持し、状態と再試行ボタンを表示します。保存されていない用途を取得前に選ぶと、選択を維持したまま通常用途の保存データを明示して表示します。
- 固定アーカイブ全16件を保持。一次資料で確認できたリンク・記述・日付を修正し、確認できない記事は未検証と明記して無関係なリンクを非表示にしています。
