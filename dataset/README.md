# Private Decisions v5 — 再利用できる判断評価セット

2026-09-30作成。公開問題をコピーせず、固定seedとコードから生成した評価専用データ。モデルの回答やLLMによる採点を正解ラベルに使用していない。

現行データは[private-decisions-v5](private-decisions-v5/)。v1〜v4はAPIへ送っていない開発版。本公開版には含めず、評価にも混ぜない。

## 内容

| 課題 | easy / medium / hard | 正解の独立検証 |
|---|---|---|
| policy: 例外付き規則適用 | 4 / 6 / 10規則。式の原子条件1 / 2 / 3個 | 式評価とSQLite |
| temporal: 更新・取消の状態追跡 | 4 / 8 / 8容器、5 / 12 / 22イベント、0 / 2 / 4取消 | 順方向シミュレーションと逆方向追跡 |
| schedule: 制約付き作業割当 | 3 / 5 / 7作業。4担当者、3時間枠、4候補 | 手続き的検証とSQL |

各群easy32、medium32、hard120の184独立問題。3群で552問。各セルは日英半数、正解A〜Dを均等化。各群hardの固定20問には候補割当反転と翻訳を追加し、120変形を含む計672件。変形を独立問題へ加算しない。

正解は常に一意。policy-hardは例外を無視すると異なる操作を選ぶ。temporal-hardは取消を無視すると別の場所になり、逆追跡が4段以上になる。scheduleの誤答候補は各1個の条件違反を持つ。

## ファイルと分離

- `items.jsonl`: 入力、正解、抽象構造、検証根拠を含む評価器用の完全版。
- `public-inputs.jsonl`: IDとAPIへ送るpayloadだけ。評価器側の正解を含まない入力専用ファイル。現在は本リポジトリで公開。
- `validation.json`: 検査件数、正解位置の分布、seed、SHA256。
- `review-examples.json`: 現行版の各課題・難易度・言語の閲覧例。

`items.jsonl`のレコードには`id`, `version`, `family`, `difficulty`, `language`, `independent_item`, `seed_key`, `payload`, `gold_choice`, `gold_internal`, `option_internal_order`, `abstract`, `witness`がある。変形には`base_id`, `variant`も付く。**モデルへ渡すのは`payload`だけ**。正解やwitnessを一緒に送らない。

候補反転では文字ラベルA〜Dを維持して内容をA↔D、B↔Cへ移す。正解と内部候補の対応も変更する。対応比較は文字ラベルではなく`option_internal_order`で復元した意味上の候補を比べる。作業割当の根拠は`candidate_violations_by_label`で表示候補へ対応する。

## 新しいセットを作る

実験の親ディレクトリで実行。Python標準ライブラリだけで動き、APIキーやネットワークは不要。

```bash
python3 generate_dataset.py --seed experiment-2026-10-b --output /tmp/decision-test-b
```

同じseedとversionなら同じ`items.jsonl`になる。既存ディレクトリは上書きしない。出力には生成器と別実装の正解検証器のハッシュも記録される。今回使った問題を完全再生成する場合:

```bash
python3 generate_dataset.py \
  --seed liquid-private-decisions-20260930-a7e4169f \
  --version private-decisions-v5 \
  --output /tmp/decision-test-reproduced
```

期待される`items.jsonl`のSHA256:
`ae041f64200422422f8cb1b3307c579a697ed10ca11e9b528bec4e7e1d0f6f60`

今回の`steady_run.py hard`は、評価前に固定した現行v5を指す。新しいセットは自動送信しない。次のモデルやAPIで使うときは、対象モデル・入力形式・件数・指標を定めてから入力ファイルを選ぶ。

## 評価の仕様

事前指定の主要検定は各課題hard120問、一様ランダム4択25%に対する片側の正確二項検定。3群をHolm補正（family-wise α=0.05）。各群の95% Wilson区間も併記する。固定ラベルの常時選択は各セルで25%。言語・難易度・変形は診断的内訳。

同じ入力を再試行して成功例だけ採ることはしない。通信失敗は別件として記録し、最初のHTTP200だけを採点。正常HTTP200の形式違反も正答率の分母に含めて不正解とする。必要な件数が揃わない場合は検定を未完了と表示する。

同一入力の再送対照60件は[fixtures/hard-repeat.json](../fixtures/hard-repeat.json)に別保存。追加の独立問題ではなく、本試験後に加えた探索的対照である。

## 適用範囲

このセットは合成された明示規則への適合を測る。実世界の知識、倫理判断、人間の価値観、作業計画の生成・最適化を全面的に測るものではない。easy等の名前は構造上の複雑さで、人間の難易度評定ではない。全て固定テンプレートなので自然言語の多様さにも限界がある。

policyは適用可能な規則が2つ以上ある条件で生成するため、「どの規則にも該当せず既定操作に戻る」分岐はこの版の評価対象に入っていない。

作業割当の候補は、正解を決める前に対称に生成することで、候補の多数派だけを選ぶ抜け道を抑えた。全候補が同時作業衝突を避けて生成されるため、衝突解消を評価できない。一部の問題は前後関係を持たない。型や制約を増やす場合は別バージョンにする。

公開問題の暗記は避けたが、既知の課題形式まで学習に含まれていないとは保証できない。今回の問題はLiquidへ送信済み。今後の回帰テストでは同じ固定セットを使い、新しい評価では別seedを作り、モデルの回答を見る前に固定する。固定セットと生成器を本リポジトリで公開した。privateという版名は作成時の内部名であり、現在の非公開性を意味しない。

設計監査と偏り修正は[公開版の方法と来歴](../METHODOLOGY.md)、今回の結果は[RESULTS.md](../RESULTS.md)を参照。
