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

## GA4 Measurement Protocol 用の任意環境変数
- GA4_ENABLED=false
- GA4_MEASUREMENT_ID
- GA4_API_SECRET

`GA4_ENABLED=true` のときだけ、Cloud Run 側から GA4 Measurement Protocol でイベントを送信します。
未設定または `false` の場合は送信しません。`GA4_API_SECRET` はコードに直書きせず、
Cloud Run の環境変数または Secret Manager から注入してください。

GA4で見る主なイベント:
- `streamlit_page_view`
- `checkout_session_created`
- `form_displayed`
- `pdf_generated`

Wix LP から Cloud Run へ遷移するボタンURL例:

```text
https://ai-uranai-h1-155905710900.asia-northeast2.run.app/?utm_source=instagram&utm_medium=paid_social&utm_campaign=ryujin_uranai_lp&utm_content=wix_cta
```

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
- max instances: 1

Streamlit はセッションやアップロード中のファイル状態をインスタンス内に保持します。
Cloud Run で複数インスタンスに分散されると、画面表示を処理したインスタンスと
`/_stcore/upload_file/...` の PUT を処理するインスタンスがずれ、ファイル選択直後に
400 が返ることがあります。まず本体サービスは最大インスタンス数を 1 にしてください。

```powershell
gcloud run services update ai-uranai-h1 `
  --region=asia-northeast2 `
  --max=1
```

デプロイ時に revision 単位で指定する場合は `--max-instances=1` を使います。

Session Affinity は緩和策として使えますが、Cloud Run では常に同じインスタンスへ
送られる保証まではないため、このアプリではまず最大インスタンス数 1 を優先します。

## メモ
- Secret は Cloud Run の環境変数または Secret Manager から注入してください。
- フォント2種と miko.png は、今回の出力一式には含めていません。既存ファイルを同じ配置で入れてください。
