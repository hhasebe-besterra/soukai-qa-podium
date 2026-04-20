# 株主総会 演台用Q&A

2026年4月23日 ベステラ㈱ 株主総会 議長演台モニター用 Q&A 検索サイト。

## 公開URL

**https://hhasebe-besterra.github.io/soukai-qa-podium/**

## データソース

Google Sheets を**5分おきに自動同期**しています（GitHub Actions）。
Sheets を編集すると、最大5分遅延で演台サイトにも反映されます。

- Sheet: `https://docs.google.com/spreadsheets/d/1-Bn5jOo2NFTBBu2Rt5LWUzdmqfy01vVR2WkfTOglYB8/edit`
- Sync workflow: `.github/workflows/sync.yml`（cron `*/5 * * * *`）
- 内容に変化がないときは commit しないので、無駄な push は発生しません

## セキュリティ

本体HTMLは **AES-256-GCM + PBKDF2(SHA-256, 310,000回反復)** で暗号化されており、
正しいパスワードが入力されるまでブラウザで復号できません。

- リポジトリ自体は公開ですが、Q&A本文・回答は暗号文としてのみ格納
- 復号はブラウザ内で完結（Web Crypto API）
- パスワードは関係者のみに共有

パスワードを変更したい場合は、GitHub リポジトリの `Settings → Secrets → Actions` に
`PODIUM_PW` を登録すると、ビルド時にそれが採用されます（未設定なら `besterra`）。

## 使い方

1. アクセスしてパスワードを入力
2. 左ペインで検索・Q番号ジャンプ（例：`42` → Enter、`F22` → Enter）
3. 候補を選択 → 右ペインに回答表示
4. **F** キー or 「🖥 演台モード」で全画面特大表示
5. **A+/A−** で文字サイズ調整、**📋コピー** で回答をクリップボードへ
6. **Esc** で演台モード解除

## 手動ビルド（ローカル）

```bash
python build.py
```

Google Sheets を取得して `index.html` を再生成します。

## 注意

- 株主総会当日限定の公開を想定。終了後はリポジトリを private 化または削除してください
- `besterra` は辞書単語のため、長期公開には向きません
- 5分おきの Actions 実行は GitHub の最短 cron 間隔です（GitHub側負荷で数分ズレることあり）
