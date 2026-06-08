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
