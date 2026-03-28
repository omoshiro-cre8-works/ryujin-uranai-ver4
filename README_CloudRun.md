# 龍神AIうらないアプリ Cloud Run 用メモ

## 必要ファイル
- app.py
- config.py
- requirements.txt
- Dockerfile
- .dockerignore
- .env.example
- services/
- ui/
- models/
- miko.png
- NotoSerifJP-Regular.ttf
- SawarabiMincho-Regular.ttf

## Cloud Run で最低限設定する環境変数
- APP_PASSPHRASE
- GEMINI_API_KEY
- APP_ENV=prod
- LOG_LEVEL=INFO
- GEMINI_MODEL=gemini-2.5-flash
- STRIPE_SECRET_KEY
- STRIPE_PRICE_ID_REGULAR

## Stripe キャンペーン切り替え用の任意環境変数
- STRIPE_PRICE_ID_CAMPAIGN
- CAMPAIGN_END_AT
- CAMPAIGN_TIMEZONE

## Stripe 価格切り替えの挙動
- `STRIPE_PRICE_ID_CAMPAIGN` と `CAMPAIGN_END_AT` の両方が設定されている間のみ、キャンペーン価格を使います。
- 現在時刻が `CAMPAIGN_END_AT` より前ならキャンペーン価格、終了後は通常価格へ自動で戻ります。
- `CAMPAIGN_END_AT` にタイムゾーン情報がない場合は `CAMPAIGN_TIMEZONE` の時刻として解釈します。

## 初期推奨設定
- concurrency: 1
- timeout: 600
- min instances: 0
- max instances: 3

## メモ
- Secret は Cloud Run の環境変数または Secret Manager から注入してください。
- フォント2種と miko.png は、今回の出力一式には含めていません。既存ファイルを同じ配置で入れてください。
