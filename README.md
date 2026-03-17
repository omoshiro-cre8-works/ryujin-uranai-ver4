# uranai_app_stage3_base

## 概要
`uranai_app_stage3_base` は、AIうらないアプリ「龍神さまのお告げ」の現時点での基準版フォルダです。  
この版では、以下を両立することを目指しています。

- `v14` 時点で完成した見た目・入力UI・鑑定仕様の維持
- 第3段階としての責務分離
- 今後の改善・保守・再構築のしやすさ

現在の構成では、次の責務を分離しています。

- 設定値管理 → `config.py`
- データモデル → `models/`
- 入力検証 → `services/validation_service.py`
- プロンプト生成 → `services/prompt_service.py`
- 出力整形 → `services/formatter_service.py`
- Gemini呼び出し → `services/fortune_service.py`
- PDF生成 → `services/pdf_service.py`
- CSS / UI部品 → `ui/`

---

## このフォルダの位置づけ
このフォルダは、**今後の開発の基準版**です。

- 現在の正式な作業対象: `uranai_app_stage3_base`
- 過去版の退避先: `uranai_app_old`

今後、仕様変更や大きな修正を行う場合は、まずこのフォルダを複製してから作業することを推奨します。

---

## 主な機能
- 合言葉入力による利用制限
- 氏名（姓 / 名）入力
- 生年月日入力（未選択対応）
- 出生時刻の精度選択
- 相談カテゴリ最大3つ選択
- 補足自由記述
- 手相画像アップロード（最大2枚）
- 左手 / 右手指定
- Gemini による総合鑑定
- PDF形式での鑑定結果保存
- スマホ表示への配慮

---

## 必要ファイル
このフォルダ直下に、少なくとも以下を置いてください。

- `app.py`
- `config.py`
- `models/`
- `services/`
- `ui/`
- `.env`
- `miko.png`

必要に応じて以下も置いてください。

- `NotoSerifJP-Regular.ttf`
- `SawarabiMincho-Regular.ttf`

---

## `.env` の置き方
`.env` は **このフォルダ直下** に置きます。  
ファイル名は **`.env`** です。

例:
- `uranai_app_stage3_base/.env`

`.env.example` をコピーして `.env` にリネームし、各値を設定してください。

---

## 起動方法

### 1. VS Code でフォルダを開く
`uranai_app_stage3_base` フォルダ自体を VS Code で開きます。

### 2. ターミナルで起動
以下を実行します。

```powershell
py -m streamlit run app.py
```

---

## フォルダ構成
```text
uranai_app_stage3_base/
├─ app.py
├─ config.py
├─ .env
├─ .env.example
├─ miko.png
├─ README.md
├─ models/
│  ├─ __init__.py
│  └─ schemas.py
├─ services/
│  ├─ __init__.py
│  ├─ validation_service.py
│  ├─ prompt_service.py
│  ├─ formatter_service.py
│  ├─ fortune_service.py
│  └─ pdf_service.py
└─ ui/
   ├─ __init__.py
   ├─ styles.py
   └─ components.py
```

---

## 主要ファイルの役割

### app.py
- Streamlit の入口
- セッション状態の管理
- 画面全体の流れ制御
- 各 service / ui の呼び出し

### config.py
- 環境変数読み込み
- アプリ定数の一元管理

### models/schemas.py
- データモデル
- JSON schema
- 共通の型定義

### services/validation_service.py
- 入力値の検証
- MIME判定
- 生年月日 / 時刻 / 手相関連の入力チェック補助

### services/prompt_service.py
- Gemini に渡す system prompt / user prompt の生成

### services/formatter_service.py
- 鑑定結果の整形
- 英単語混入抑制
- 表記ゆれ補正
- 段落調整

### services/fortune_service.py
- Gemini クライアント生成
- 画像パート生成
- 鑑定実行

### services/pdf_service.py
- 日本語フォント登録
- PDF鑑定書生成

### ui/styles.py
- CSS の定義

### ui/components.py
- 再利用する UI 部品
- 余白、結果ボックス、左右選択などの補助

---

## 動作確認済み項目
現時点で、以下は確認済みです。

- 合言葉が通る
- 生年月日未選択でエラーになる
- 出生時刻「不明」で時分が消える
- 手相左右未選択でエラーになる
- 鑑定ができる
- PDFが作れる
- スマホ表示が大きく崩れない

---

## よくあるエラーと対処

### 1. No API key was provided
原因:
- `.env` が正しい場所にない
- `GEMINI_API_KEY` が未設定

対処:
- `.env` をこのフォルダ直下に置く
- `GEMINI_API_KEY=...` を確認する

### 2. APP_PASSPHRASE が未設定
原因:
- `.env` に `APP_PASSPHRASE` がない

対処:
- `.env` に合言葉を設定する

### 3. 巫女画像が表示されない
原因:
- `miko.png` がない
- `MIKO_IMAGE_PATH` の設定がずれている

対処:
- `miko.png` をこのフォルダに置く
- `.env` の `MIKO_IMAGE_PATH` を確認する

### 4. PDFで日本語が文字化けする
原因:
- フォントファイルがない
- フォントパスがずれている

対処:
- `NotoSerifJP-Regular.ttf` などを置く
- `.env` の `PDF_FONT_PATH_1`, `PDF_FONT_PATH_2` を確認する

### 5. import error / NameError
原因:
- 分割後ファイルの置き換えミス
- 古いファイルが混ざっている

対処:
- `uranai_app_stage3_base` の中身を基準にする
- `uranai_app_old` 側のファイルを混ぜない

---

## 今後の運用ルール
- 現在の基準版は **`uranai_app_stage3_base`**
- 過去版は **`uranai_app_old`**
- 大きな修正前にはフォルダを複製する
- 仕様変更をしたら、README か仕様メモも更新する
- 不具合修正後は、最低限
  - 起動
  - 合言葉
  - 鑑定
  - PDF
  を再確認する

---

## 今後の候補タスク
- `.env.example` の維持更新
- `requirements.txt` の見直し
- `ui/form_sections.py` へのさらなる分割
- エラーメッセージ改善
- 将来の FastAPI / フロント分離に向けた整理

---

## 補足
この README は、現時点の基準版向けのたたき台です。  
今後、公開を意識する段階になったら、以下を追加するとよりよいです。

- アプリの利用目的
- 個人情報の扱い方針
- 注意事項
- バージョン履歴

---

## 運用メモ

現在の基準版フォルダは `uranai_app_stage3_base` とする。  
通常の修正・確認・軽微改善は、このフォルダを基準に行う。

過去版・途中版は `uranai_app_old` に保管し、基準版へ混在させない。

大きな修正を行う前は、`uranai_app_stage3_base` を複製してから作業する。  

修正後は最低限、次を確認する。

- 起動できる
- 合言葉が通る
- 鑑定できる
- PDFが作れる

仕様や構成を変更した場合は、必要に応じて次も更新する。

- `README.md`
- `.env.example`
- `requirements.txt`

当面は `uranai_app_stage3_base` を正式な作業基準とし、  
安定度がさらに高まった段階で、必要に応じて `v1` 系の正式名称へ移行する。

---

## 公開直前の確認メモ

対象: `uranai_app_stage3_base`

### 目的
紹介ページから実際に利用したときに、ユーザーが迷わず使え、内容・表示・導線に問題がないかを最終確認する。

### 1. 紹介ページ確認
- [ ] 紹介ページが正常表示される
- [ ] AIうらないの内容が分かる
- [ ] 免責事項が読める
- [ ] 特商法表記への導線が分かる
- [ ] アプリ内の説明と大きく矛盾していない

### 2. アプリ起動確認
- [ ] アプリが正常起動する
- [ ] 合言葉入力欄が表示される
- [ ] 正しい合言葉で先へ進める
- [ ] 初期表示が崩れていない

### 3. 重要事項表示確認
- [ ] 重要事項ボックスが目立つ
- [ ] 内容が分かりやすい
- [ ] 「参考情報」「重要判断には使わない」「保存しない」が伝わる
- [ ] ご利用前のご案内が開ける

### 4. 入力確認
- [ ] 氏名入力ができる
- [ ] 生年月日入力ができる
- [ ] 出生時刻切り替えが正常
- [ ] 相談カテゴリが選べる
- [ ] 手相画像アップロードができる
- [ ] 左右選択ができる
- [ ] 案内文が自然

### 5. 鑑定確認
- [ ] 鑑定ボタンで正常に実行される
- [ ] 鑑定結果が表示される
- [ ] 結果が極端に崩れていない
- [ ] エラー表示が不自然でない

### 6. PDF確認
- [ ] PDF保存ボタンが表示される
- [ ] PDFが正常にダウンロードできる
- [ ] 日本語が文字化けしていない
- [ ] 巫女画像が表示されている
- [ ] 見た目が実用上問題ない
- [ ] 句読点や改行の崩れが実用上気にならない

### 7. スマホ確認
- [ ] スマホでも大きく崩れない
- [ ] 入力しやすい
- [ ] 鑑定まで進める
- [ ] PDF保存まで進める

### 8. 最終判断
- [ ] 公開可
- [ ] 軽微修正後に公開可
- [ ] 公開前に再修正が必要

### 気になった点メモ
- UI:
- 鑑定内容:
- PDF:
- 導線:
- スマホ:

### 運用メモ
紹介ページ → アプリ → 鑑定 → PDF保存までを通して確認し、大きな破綻がなければ公開可と判断する。  
気になる点があっても、重大不具合でなければ軽微修正後に公開可とする。
