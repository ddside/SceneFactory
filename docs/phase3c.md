# Phase 3C — 屋内環境・生成家具・スキル蓄積

アプリ0.6.0。Python 3.12 / uv、Blender 4.5 LTS内蔵Python 3.11の分離、
既存Registry、Recipe、Catalog、Revision、acceptedの境界を維持した。
自然言語の解釈・不足スキルの実装・実画像の判断はCodexが担当する。
新しいLLMサービス、パーサー、エージェント基盤は導入していない。

## スキルと生成物

全て`@1.0.0`。共通Leafは`furniture_part`のみで、閉じた面取り直方体を生成する。
独立した部材のRecipeで家具を組み立てる。寸法はm、底面Z=0。

| Skill | 主な独立部材 |
|---|---|
| desk | 天板、4脚、幕板。低机・会議机にも寸法変更で再利用 |
| chair | 座面、4脚、背支柱、背板 |
| shelf | 4支柱、3棚板、背板。Rackとしても利用 |
| cabinet | 底板、側板、天板、背板、棚板、2扉、取手 |
| storage_box | 底板と4壁の開放容器 |
| monitor | 台座、支柱、筐体、画面パネル |
| partition | 2脚とパネル |
| counter | cabinetと作業天板 |
| product_package | 閉じた箱と薄いラベル板 |
| bed | 脚、フレーム、マットレス、ヘッドボード、枕 |
| light_fixture | 取付板と拡散板。照明形状のみ |
| workstation | desk + chair + monitor。机のLength出力でモニターを接地 |
| filing_cabinet | 本体、4引き出しの前板・トレイ・取手 |

`width/depth/height/thickness`と用途別寸法をSchemaで制限する。chairは
`seat_height`も持つ。Leafは`bevel`と6種の初期surface設定を持つ。
表面の実際の材質は通常の`appearance` MaterialRefで指定し、surfaceを
新しいMaterial Catalogとして扱わない。部材の角は低密度の2segment bevel。
装飾、曲面脚、ヒンジ機構、引き出しの可動機構、印字は未実装。

### 識別・将来の損傷

Recipeのlocal_key→既存child_id規則→論理node ID→Artifact IDを維持する。
各部材は別Object、同条件のMeshだけを共有する。部材単位で選択・分離できる。
`node_seed`、寸法、transform、lineage、source skill/version、MaterialRefは
通常のPlan/Artifact/skills lockで追跡できる。

`SceneSpec.interior.items`に用途・正常状態・支持関係を明示する。
Planの`interior_metadata`および実検証の`kind=interior`結果に部材ID、測定bounds、
支持対象、Skill/Assetの出典を記録する。生成Meshにも`component_state=normal`を保存。
部材接続は接触グラフで検査し、浮いた部材と正体積の貫通を拒否する。
将来は正常Specから別Revisionで転倒・移動・破損状態を派生させる。
このPhaseでは正常状態以外を拒否し、損傷メッシュや剛体を生成しない。

## 既存Assetと生成の選択

1. validated Skill Registryを検索する。
2. Asset Catalogを検索する。
3. 寸法適合性・形状・品質・ライセンス・再利用性を比較する。
4. 適切なSkill、既存Asset、両者のRecipeを選ぶ。
5. 重要な不足に限って候補Skillを開発する。

単純な家具は寸法変更可能なRecipe、装飾や実物モデルはライセンス確認済みAssetが適する。
取得時だけProviderを呼び、生成時は固定Refと凍結リソースを使う。
Aでは既存の自作CC0 Local glTF fixtureを小さな抽象彫刻として家具上に配置した。
この低密度モデルを実物の高品質家具と偽らない。外部モデルの階層・複数Mesh・出典・
hashを維持する既存asset_instance経路をそのまま使用する。
PBR/UV/Shader検証もPhase 3Bを再利用する。今回Provider変更やライブ再取得はない。

## 不足スキルの追加（Scene E）

`filing`でRegistry/Catalogを検索し、対応候補がないことを
`artifacts/phase3c-skill-gap-before.json`へ記録した。扉式cabinetを引き出し式と
呼び替えず、既存Leafを組み合わせる汎用filing_cabinet Recipeを追加した。

1. candidate manifest、独立部材、寸法式、純粋contract、実Mesh validatorを定義。
2. Recipe展開、寸法変更、安定ID/seed、異常接続の単体テストを実行。
3. passing JUnit XMLを指定して既存`skills validate --activate`を実行。
4. 実Blenderで各2例を生成・保存・再読込し、Artifactと構造digestを照合。
5. hashで固定した証拠を伴ってvalidatedへ移行。
6. オフィス倉庫と別の店舗バックヤードで同じSkillを使用。

部材・pure contract・共通helperをbinding support_filesに含める。
検証対象コードや契約を変更したら証拠を更新する。candidate、stale evidence、
失敗した登録試験を通常生成へ通さない。これはCodexが既存登録機構を使う運用であり、
アプリが任意のコードを自動承認する機構ではない。

## SceneSpecと配置

`interior`は任意追加のversion 1契約。古いSpecの意味は変えない。

```json
{
  "schema_version": 1,
  "minimum_passage": 0.8,
  "rooms": [{
    "room_id": "building.main.room.01",
    "purpose": "work_area",
    "requirements": {"workstation": 6, "desk": 6, "chair": 6, "monitor": 6}
  }],
  "items": [{
    "node_id": "building.main.room.01.furniture.workstation.01",
    "room_id": "building.main.room.01",
    "semantic_type": "workstation",
    "initial_state": "normal",
    "support": {"kind": "floor"},
    "placement": {"mode": "explicit", "facing": 0, "minimum_clearance": 0.08}
  }]
}
```

この断片は契約の説明で、完全なSceneSpecではない。

- 矩形、直交方向、鉛直家具、m単位を基本とする。形状変更はscaleより寸法パラメータ。
- `explicit`は明示座標。`facing`は0/90/180/270度のZ回転に一致させる。
- `wall_aligned`は指定壁までの距離をminimum_clearanceに一致させる。
- `near_wall`はminimum_clearance以上、さらに0.3m以内。
- `centered`は部材boundsのXY中心を部屋中心に一致させる。
- 全モードで室内bounds、壁clearance、床〜天井の高さを検査する。
- `floor`は最下部が床Z=0。`on_top`は実在するfurniture_partの上面への接触と
  XY支持範囲を検査。`ceiling`は建物のceilingに上端を接触させる。
- 箱を棚板上に置く場合、棚全体のboundsへの接触で代用しない。
- 家具間の交差は部材box同士で検査するため、棚の空間内に箱を配置できる。
- 用途別requirementsはRecipe展開後のSkillごとの正確な数を要求する。
- 接地家具の集合boundsを保守的な2D障害物として使う。ドア幅、室内側進入領域、
  最小通路幅を検査し、入口から幅を持った空間へ進入できることを確認する。
- 0.15m以下の格子と半通路幅+半セル対角の膨張で接続を判定する。
  指定通路幅の二乗以上の到達不能な自由領域を部屋の分断として拒否する。
  小ポケットや家具の内側へ全て到達できることは要求しない。
- 実Blender検証では保存・再読込した全Mesh頂点を部屋座標へ変換して再評価する。

これは保守的なAABB検証であり、曲面形状の厳密衝突、可動扉の全動作域、避難法規、
アクセシビリティ基準、ロボット経路計画の保証ではない。高度な間取り最適化もない。

## 部屋パターンとチャット運用

`interior_layout.interior_scene(kind)`と`room_pattern`が通常の編集可能なSpecを作る。
Living / Bedroom / Simple Kitchen / Work Area / Meeting / Storage / Retail / Backroomに対応。
反復配置は安定した番号IDで展開し、countはrequirementsで検査する。
独立した汎用ソルバーやcount専用の第二実行モデルは設けない。

`apply_materials`は既存のappearanceとMaterialRefを家具部材へ結び付ける。
木材、金属、塗装、暗色画面などの数値Principled PBRであり、繊維や木目を新たに
取得したわけではない。必要なら通常のCatalog MaterialRefへ差し替えられる。

```sh
uv run --locked scene-factory generate artifacts/my-office --proposal examples/interiors/office.proposal.json
uv run --locked scene-factory resume artifacts/my-office
uv run --locked scene-factory edit artifacts/my-office --proposal examples/interiors/office-edit.proposal.json
```

Blenderの場所は既存設定/環境変数で指定する。実画像を全て閲覧してから、既存の
image-bound VisualReviewとreviewコマンドで受理する。PNG生成だけでvisual passedにしない。
新しい`interior` profileはarchitectural + appearanceの実証に加えて、再読込済みの
interior domain evidenceを要求する。古いprofileの意味は維持する。
天井取付物は断面preview時にcoverと一緒に一時的に非表示にする。保存シーンからは削除しない。

## 受入・試験・性能

実施結果は下記に記録する。生成・ログ・XML・画像はignored artifacts配下に保持し、
ここへ数値と対応する検証範囲を記録する。入力例だけをexamples/interiorsへGit管理する。

## 残る制限とPhase 3D

macOSでの実測であり、Ubuntu 24.04 / CUDA / OptiXの実機検証は未実施。
USD / Isaac Sim互換性はnot_runのまま。今回の受理はinterior profileの範囲に限定する。
損傷、転倒、物理、瓦礫、LOD、部分再生成キャッシュ、高度な自動間取りは未実装。
ベッド・キッチンはパターン契約と構成Skillの実登録検証までで、代表画像はA〜Dに絞る。
正常部材・支持関係・再利用スキルの基盤上でPhase 3Dへ進めるが、破壊処理前に
共有Meshをcopy-on-writeで分離する必要がある。損傷状態は別契約・別検証として追加する。

### Scene A〜Eの実施結果

| Scene | 実施内容・結果 |
|---|---|
| A | 1室リビング、簡易座席2、低机、棚、収納、箱型小物、天井器具。既存Localモデルを収納上に併用。interior受理 |
| B | 3室+廊下、Workstation 6、会議机+6椅子、倉庫2棚+4箱+filing_cabinet。interior受理 |
| C | 売場2棚+8商品+counter、別室バックヤード2棚+4箱+filing_cabinet。interior受理 |
| D | BのWorkstation 05/06だけを削除し、倉庫shelf.02を追加。4セット・3棚を実画像で確認し、新Revisionを受理 |
| E | 不足確認→candidate実装→34単体試験のJUnit→各2例の実保存/再読込→validated。B/Cで同一バージョンを再利用。近接画像で4引き出し・取手を確認 |

DのSpec差分は2ノード削除・1ノード追加で、共通ノードの変更はゼロ。
appearanceでは対応する部材bindingだけを除去/追加し、共通binding/MaterialRefを維持した。
共通262 Artifactのgeometry digestを維持し、旧acceptedのhashを再検証した。
B→D→B→Dの公開参照切替を実行し、再生成なしのRollback往復を確認した。
各acceptedのbundleは削除・上書きしていない。

証拠は`artifacts/phase3c-acceptance/`に保持する。
`edit-and-rollback-evidence.json`、`final-reopen-evidence.json`、
`performance-and-acceptance.json`にID・測定・検証操作を記録する。
各プロジェクトの不変Attempt、Quality、VisualReview、Acceptanceが出力との対応を保持する。

実閲覧した最終画像はA/B/C/Dそれぞれoverview/top/interiorの計12枚とE近接1枚。
対応するPNGのpath/hashは各VisualReviewとAcceptance bundleに固定されている。
Eは`artifacts/phase3c-acceptance/filing-cabinet-preview/preview.png`。
最初のA断面で天井器具だけが見えた問題はpreview cover連動で修正し、画像を再確認した。
屋内形状と用途を識別できる簡略品質であり、photorealisticとは評価していない。

### 実測性能

macOS / Apple M5、Blender 4.5.15 LTS、Cycles CPU、384px、16 samples、denoise。
回帰試験と一部並行した観測値で、厳密な単独ベンチマークではない。
生成秒はBlender build workerの検証・保存込み。Preview秒は3 workerの合計で、
再読込・再検証・レンダリング込み。アプリ側compile/起動待ち等を含む全所要時間ではない。
メモリはbuild workerのpeak RSSで、アプリや他プロセスとの合計ではない。

| Scene | 生成秒 | Preview計秒 | Mesh Object / 共有後Mesh | 頂点 | 面 | 配置単位 | 使用Material | build peak MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 1.215 | 4.257 | 61 / 35 | 1704 | 1594 | 9 | 35 | 239.9 |
| B | 4.066 | 13.339 | 248 / 54 | 7608 | 7124 | 24 | 54 | 256.8 |
| C | 2.094 | 8.483 | 119 / 44 | 3532 | 3302 | 20 | 44 | 235.9 |
| D | 3.546 | 10.839 | 220 / 54 | 6712 | 6284 | 23 | 54 | 252.8 |

頂点/面はObjectごとの合計で、共有データを重複計上する。配置単位はinterior.itemsの数で、
Workstationを1と数え、照明・箱・小物も含む。内部の机/椅子/モニター数は別のrequirementsで検査する。
Mesh cacheは寸法・bevel・surface・実効MaterialRef/UV/regionが同じ場合だけ共有し、
異なる材質指定が別家具を書き換えないようにする。大規模LODや増分キャッシュはない。

### 検証コマンドと範囲

```sh
uv sync --locked
uv run --locked pytest tests/test_furniture.py --junitxml=artifacts/phase3c-furniture-final.xml
uv run --locked scene-factory skills validate furniture_part --activate --test-report artifacts/phase3c-furniture-final.xml
# 続いて依存順に desk/chair/shelf/cabinet/storage_box/monitor/partition/counter/
# product_package/bed/light_fixture/workstation/filing_cabinetを同じ既存登録APIで検証。
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -q --junitxml=artifacts/phase3c-regression-final.xml
```

上のBlenderパスはこのMacで実行したコマンドの記録であり、アプリへの埋め込みではない。
sandbox内起動は利用できないため、実Blender試験は許可済みの制限外CLI実行で行った。
このセッションでは必要に応じ`UV_CACHE_DIR=.uv-cache`を指定した。
uvは0.11.26、アプリPythonは3.12.13、Blender Pythonは3.11.15。新しい依存追加はない。

新規純粋試験は寸法、Recipe、ID/seed、支持/接続、用途別数、編集と材質参照の保持、
室外、浮遊、交差、ドア、通路分断、南壁clearance、未宣言Mesh等を検査する。
新規実Blender試験はA/B/C保存・再読込、共有Mesh、天井preview metadata、Dの形状維持、
実際に保存した法線反転/正常状態改変/材質欠落の拒否を検査する。
既存の不正AssetRef/MaterialRef、Manifest、candidate/stale証拠、登録用JUnit失敗、
atomic accepted公開失敗と旧bundle保護の試験も保持する。
公開途中のI/O障害と登録JUnit失敗は明示的なunit fault injectionであり、
実BlenderでI/O故障を起こした証拠と混同しない。

最初の全回帰でPBR編集の参照不整合を検出し、対象bindingだけを更新する修正と試験を追加した。
さらに、南壁近傍の格子は入口の実幅内だけを通過可能に限定し、未宣言Meshによる占有漏れを拒否した。
最終全回帰は **383 passed / 4 skipped**（183.89秒）。既存311件と新規72件を含む。
実Blender回帰は50件（既存42 + 新規8）。通常回帰の残り333件は純粋/CLI/障害注入試験。
4 skippedは変更していないProviderのopt-inライブAPI試験であり、互換性確認済みとは扱わない。
別枠で新規14 Skill×各2例=28例の実Blender生成・保存・再読込登録を実施した。
登録は56回のbuild/reopenプロセスに相当するが、これをpytest件数へ重複加算しない。
最終XMLは`artifacts/phase3c-regression-final.xml`。14個の最新validation pinと
6個のproposal入力を追加確認し、`git diff --check`も通過した。

必須受入A〜Eを満たした。正常屋内基盤としてPhase 3Dへの移行は可能。
ただし、上記未検証プラットフォームと損傷/物理/USDの別受入は引き続き必要。
