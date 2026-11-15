# Phase 2A — 共通契約とスキル基盤

実装・検証日: 2026-11-15 (America/New_York)。アプリversion 0.2.0。
macOS 26.6.2 / Apple M5 / arm64 / 16GB、uv 0.11.26、アプリPython 3.12.13、
Blender 4.5.15 LTS (5afeabba6097)、内蔵Python 3.11.15で検証した。
以下の「対応」は実装範囲であり、Ubuntu実機での動作確認を意味しない。

## 1. 方針とPhase 1.5への対応

既存基盤を作り直さず、v1の読込み・変換adapterを残して新規ビルドをplan経由にした。
追加の実行時依存、チャットUI、API接続、MCP、常駐サービス、キャッシュは導入していない。

| Finding | 今回の対応 | 延期したもの |
|---|---|---|
| F01 | logical node/artifactを分離。共通・skill validatorを分離。非直方体と複合を実証 | 高度なdomain条件 |
| F02 | SceneSpec v2、親子階層、依存DAG、typed ports、明示移行 | asset/material/state/constraintの新しい参照型 |
| F03 | SkillManifest、ローカル検索、許可済みentry point、状態と有効化証跡 | 外部配布基盤・自動スキル探索サービス |
| F04 | compile/ResolvedScene/BuildPlanと実行ノード境界 | 差分実行、cache、部分再生成 |
| F05 | 入力/計画/実行を分け、後からIntentを置ける境界 | SceneIntent、画像解析、自然言語自動化 |
| F06 | 段階別QualityReport。構造成功とacceptedを区別 | 自動視覚評価 |
| F07 | 品質結果を後続フローへ渡せるJSON契約 | bounded repair・自動改善 |
| F08 | schema/skill/依存/実装/環境/seed算出方式を記録 | 旧コードの自動取得・完全な再生成環境復元 |
| F09 | 既存build保存と成功版保護を維持 | Revision/Rollbackの本体 |
| F10 | 不変PNGと単一公開参照へ変更。IO故障注入で検証 | accepted Revisionへの統合 |
| F11 | protocol 2、attempt/plan digest、inventory件数・ID照合 | RPC等への置換は不要 |
| F12 | スキル別パラメータ/検証へのdispatch境界 | アセット/PBRライブラリ、損傷表現 |
| F13 | 軽量ArtifactManifestとstreaming geometry digest | 大規模最適化、LOD、instancing |
| F14 | 新しい負例、公開途中失敗、非直方体等を実Blender検証 | Ubuntu実機、途中処理resume、自動lock復旧 |
| F15 | qualityのexport/target段階をnot_runで区別 | USD本体、Isaac Sim受入 |

## 2. 実装の分割

| 場所 | 責務 |
|---|---|
| spec.py | 凍結したv1検証とv2へのdispatch |
| scene_v2.py | v2検証、純粋v1変換、別ファイルへの明示migration |
| contract_utils.py / transforms.py | 閉じた型/式/DAG/変換の共通処理。Python 3.11互換 |
| registry.py / skills/*.json | Manifestと信頼されたbinding catalogの読込み。bpyをimportしない |
| compiler.py | 純粋compile。幾何生成、subprocess、ファイル出力なし |
| artifacts.py / quality.py | 両ランタイムで利用する結果データ契約 |
| blender/engine.py | planをDAG順に実行し、登録済み関数へdispatch |
| blender/validation.py | shape-independentな共通検証とvalidator dispatch |
| blender/skills/*.py | cuboid、cylinder、recipeの実装・独立validator |
| blender/legacy_validation.py | 既存のplan無しbuildのためのPhase 1検証adapter |
| runner.py / blender/worker.py | subprocess/JSON通信、protocol、実行/再読込み |
| project.py / storage.py / png.py | staging、hash、公開参照、PNG完全性検査 |
| skill_testing.py | 明示的な実Blender登録検証と証跡を伴う有効化 |

## 3. Scene Specification v2

ルート必須はschema_version=2、scene_id、seed、units="m"、nodes。
単位はメートル、Z-up。ID、seed、位置/回転/scaleの範囲はv1を維持する。
node_idは1..64文字、ASCII英数字/`.`/`_`/`-`で先頭は英数字。
seedは整数0..4294967295、nodesは1..1000個。
配列順、Blenderの自動命名、ファイル名をIDの正本にしない。

各nodeはnode_id、skill（skill_idと正確なversion）、transform、parametersを必須とする。
parent_idは省略時null、depends_onは[]、inputsは{}。
transformはlocation、rotation_degrees（XYZ Euler）、scaleを省略可能。
初期値は[0,0,0]、[0,0,0]、[1,1,1]で、範囲は各々±10000、±360、0.001..100。
パラメータの名前・型・初期値・範囲はスキルmanifestが定義する。
未知フィールド、未登録型/スキル/版、不正値、重複ID、欠落参照、循環を拒否する。
asset/material/state/constraint等の未実装参照を任意JSONとして受け入れない。

屋根が寸法出力を使う最小例:

```json
{
  "schema_version": 2,
  "scene_id": "typed-example",
  "seed": 42,
  "units": "m",
  "nodes": [
    {
      "node_id": "body",
      "skill": {"skill_id": "box_building", "version": "1.0.0"},
      "transform": {},
      "parameters": {"height": 5}
    },
    {
      "node_id": "roof",
      "skill": {"skill_id": "roof", "version": "1.0.0"},
      "parent_id": null,
      "depends_on": ["body"],
      "inputs": {"elevation": {"node_id": "body", "output": "height"}},
      "transform": {},
      "parameters": {}
    }
  ]
}
```

ここではbody.heightが5ならroofの解決済みlocal Zは5になる。
depends_onだけではroof位置は変わらない。型付きの参照が値の受渡しを担う。

### 階層・型・変換

parent_idは空間的な所属で、local TRSは親のframeに対する変換。
world matrixはparent world × resolved local。Blenderでも実際のparentを設定し、
非一様scaleを含む階層を保存・再読込みして検証する。
depends_onは明示的な先行処理で、空間変換を与えない。
実行DAGにはparent edge、depends_on、明示typed inputのproducer edgeを含む。
親子循環と結合した依存循環をどちらも検出する。

Phase 2Aで実装した型はLengthとDimensionsのみ。
Lengthは0..1e6の有限スカラー、Dimensionsは正の3成分。
入力の最小bindingはLength→elevationで、値をnodeのlocal Z offsetへ加算する。
Dimensionsは出力・記録・型照合に利用できるが、入力の配置bindingはまだ実装していない。
Lengthはスキル寸法のローカル距離であり、任意に回転・拡縮した面を表すworld Anchorではない。
支持面/Socket/Transform/Geometry/MaterialRef/AssetRef型は未対応として拒否する。
オフセット適用前のtransformとresolved_transform、local/world matrixを分けて保存する。
現状はcompile時に解決できる値だけを扱う。実メッシュ由来のAnchor等を導入する際は、
producer実行後に解決するport状態と実測出力記録を追加し、compileに幾何生成を持ち込まない。

### v1の維持と明示移行

`migrate_v1(data, source_sha256)`は純粋関数。
4生成器のstable_id→node_id、generator→同名skill@1.0.0とし、
scene_id、seed、units、寸法初期値、底面中心原点、TRSの意味を保持する。
legacyフィールドで旧stable_id/generatorとの対応を記録する。

`migrate_file` / CLIは**別の未作成ファイル**へ排他的に書き込む。
同じ入力への出力、既存出力の上書きは拒否する。
migrationにはsource_schema_version=1、元ファイルbytesのSHA-256、migration_version=1.0.0を保存。
ファイルなしの純粋APIでhashを省略した場合は、元データのcanonical JSON hashを用いる。
新規v1ビルドは内部adapterを利用するが、ユーザーのv1原本は上書きしない。
SceneSpec schema、migration、manifest、planの各versionは別概念である。

## 4. SkillManifestと登録

`src/scene_factory/skills/*.skill.json`をGit管理する。
schema version 1、skill_id、exact version、name、description、category、tags、
kind（leaf/recipe）、parameter_schema、inputs/outputs、artifacts、implementation、
validator、dependencies、blender_compatibility、examples、validation_statusを定義する。
状態はcandidate / validated / disabled。現在は6スキル、すべて1.0.0。

| skill | 出力 | パラメータと初期値 |
|---|---|---|
| ground | Mesh geometry | width=20, depth=20, thickness=.2 |
| box_building | Mesh geometry | width=6, depth=4, height=3 |
| pillar | Mesh geometry | width=.4, depth=.4, height=3 |
| roof | Mesh geometry | width=7, depth=5, thickness=.25。任意のLength elevation入力 |
| cylinder | 非直方体Mesh geometry | radius=.5, height=2, segments=16 |
| building_recipe | Object frameと4つの子Mesh | width=6, depth=4, height=3, floor_thickness=.2, wall_thickness=.2, roof_thickness=.25, pillar_width=.4 |

寸法は全て0.01..1000メートル。cylinder.segmentsは8..128、4の倍数の整数。
円柱は底面中心原点、2N頂点・N+2面（側面quadとNGONの両cap）。
Recipeは契約実証用で、床・背面の壁1枚・角柱1本・平屋根からなる開いた構造。
高品質な建築内部を実装したという意味ではない。

### 許可リストと有効化

アプリはmanifestと`entrypoints.json`だけをデータとして読み、実装をimportしない。
bindingはレビューした`scene_factory.blender.skills.*`配下の存在する関数だけに限定する。
ASTで関数定義を確認し、呼出しはBlenderプロセスだけで行う。
helperを含む必要なsupport_filesもpinする。manifestの任意Python式や任意moduleを実行しない。
このローカルcatalogは信頼してレビューするコードの一覧であり、敵対的コードのsandboxではない。

validatedにはmanifest digest、実装/validator/helper hash、依存pin、単体試験証跡、
実Blenderのexample生成/専用検証/保存/再読込み結果と実行環境を記録する。
内容が変わって証跡が古くなれば、通常生成は拒否する。
test reportは成功caseが存在しfailure/error/skipのないpytest JUnit XMLを要求する。
開発者は該当スキルの専用単体試験を含めて実行し、無関係な試験だけを根拠にしない。
ローカル証跡は操作記録であり、第三者の署名付き証明ではない。

登録手順:

1. candidate manifest、基本/複合kind、入出力、正確な依存版、例を定義する。
2. blender/skillsに実装と独立validatorを追加する。
3. reviewed entrypointsと必要helperを追加する。中央の共通Validatorへ形状ifを追加しない。
4. schema/DAG/typed port/負例の単体試験を作り、JUnit XMLを出力する。
5. `skills validate ID --activate --test-report PATH`で全examplesを実Blender検証する。
6. 成功後だけmanifestがvalidatedへ更新される。依存スキルを先に有効化する。
7. 全回帰試験、画像確認、文書更新、Gitコミットを行う。

`--contract-only`はschema確認だけで、有効化と組み合わせられない。
candidateの試験実行は明示的なskill_validation mode内だけで許可する。
通常buildではcandidate/disabled/未登録/証跡不一致を拒否する。
`skills validate`の既定は実Blender試験だが、`--activate`がなければ状態を変更しない。
有効化はGitのソースmanifestを書き換える開発操作で、読取り専用wheel環境での更新は保証しない。

## 5. Recipeとcompile / BuildPlan

compile_scene(source, registry, source_sha256, runtime_profile, allow_candidates)は
ResolvedScene、BuildPlan、skills_lockを返す。Blenderもsubprocessも使わず、ファイルを作らない。
Registryから与えた契約と実装hashを入力とする。CLI/project層が出力を保存する。
スキル依存DAGを確認し、Recipeをstable local_keyから展開して、型付き値と変換を解決する。

Recipeのparameter式は有限な数値、3成分vector、parameter参照、add/multiplyのみ。
Python evalやscript式は受け付けない。Recipeの各子は同じskill/version契約を使い、
explicit depends_onとtyped inputで接続する。子の空間parentはRecipeのframe。
展開は最大depth 16、合計1000 nodeまで。

building_recipeではfloor→wall/pillar、wall.height→roof.elevationを明示している。
roofのlocal Zはfloor_thickness + wall.heightとなり、高さ変更に追従する。
Recipeのrootもresolved nodeとして残り、そのObject frameを子の空間的な親にする。
1つのauthoring building nodeからframe＋4 Meshの5 Artifactを追跡できる。

BuildPlan schema version 1は以下を含む。

- scene/source schemaと元bytes hash、必要なmigration情報
- 正規化/展開済みnodes、authoring sourceへの対応とlineage
- execution_orderとdependency_dag
- skill/version/pin、正規化parameters、typed input/output、解決済みlocal/world matrix
- node_seed、seed_derivation_version、compiler_version、arithmetic_version
- expected ArtifactのID、role/type、依存関係
- runtime_profile、skills_lock、resolved_scene_digest、plan_digest

plan_digestは自身のdigestフィールドを除くcanonical JSONのSHA-256。
元ファイルbytesのhashや環境も含むため、入力順/書式の変更ではdigestが変わり得る。
意味的に同じ並べ替えでnode ID/seed/実行順/生成構造は変えない。
full source hashは来歴用であり、将来の各node cache keyとして流用しない。

### ID・seed・数値規則と版固定

Recipe child IDは親IDとlocal_keyのhash、artifact IDはproducer node IDとlocal roleのhash。
表示名、配列のindex、Blenderの自動命名は使わない。
seedはSHA-256(`${scene_seed}:${node_id}`)の64桁hexとして記録する。
この方式は既存cuboid材質のID別seed導出と整合する。
無関係nodeの挿入/削除/並べ替えで既存child IDやnode seedを変更しない。

Python 3.12と3.11ではbuilt-in sumの浮動小数点加算結果に最下位桁差が出たため、
compile算術はmath.fsum、行列は12桁丸めを使う`fsum-trs-round12-v1`で固定した。
実Blenderとアプリ側で同じplanを再解決して一致することを確認した。
Python 3.12のsum変更は[Python公式の変更記録](https://docs.python.org/3.12/whatsnew/3.12.html#other-language-changes)にも記載されている。
検証器の数値許容差（相対1e-6/絶対2e-5）と、planのcanonical化規則は別の目的である。

skills lockには個別manifest版/契約hash、implementation/validator/helper hash、
正確な依存版と再帰的な依存pinを記録する。
planのruntime_profileには要求するBlender 4.5/Python 3.11系列、アプリPython、
OS/architecture、ランタイムソース群のhashを記録する。
実行結果/build metadataには実際のBlender版/build hash、内蔵Python、実行コードhashも保存する。

workerはplan digestを検査し、snapshot sourceと現在のskill pinsからplanを再compileして照合する。
aggregate runtime hashは来歴として保存し、実際の実行コードとの一致もruntime_code_matchesで報告。
無関係なCLI変更だけで過去planを無条件に使えなくする用途には使わない。
一方、skill pin、解決値、compiler契約が一致しなければ拒否する。
過去コードを自動取得しないので、古いコードが手元にない場合の完全再生成を保証しない。
画像や.blendのbytes一致、異OS間のhash一致も要件にしていない。

## 6. ArtifactManifestと検証

ArtifactManifest schema version 1のartifacts配列は、artifact_id、source_node_id、
producer_node_id、role/local_role、type、lineage、dependencies、reference、
geometry_digest、頂点/面数、bounds、local/world matrixを持つ。
node_artifactsは元authoring node ID→生成artifact ID一覧を示す。
Recipeの子はproducer_node_idで個別識別し、source_node_idで元buildingを追跡できる。

```text
source building.main
  Object frame             producer building.main
  Mesh floor.geometry      producer hash(building.main, floor)
  Mesh wall.geometry       producer hash(building.main, wall)
  Mesh pillar.geometry     producer hash(building.main, pillar)
  Mesh roof.geometry       producer hash(building.main, roof)
```

Phase 2AのtypeはMeshとObject（Emptyのみ）。Collection/Instanceは未対応として拒否する。
Mesh ArtifactはBlender ObjectとMesh dataを一つの生成物として参照する。
reference.object/meshは現在の診断用名で、識別の正本はcustom propertyのartifact_id。
名前だけを変更してもartifact ID/構造digestは変わらないことを実機試験した。
スキルが最初に宣言したartifactをそのnodeの空間frameとして扱う。

共通Validatorは計画に対するartifactの欠落/追加/重複、metadata、有限座標/変換、
単位、実parent、local/world行列、型、typed input記録、依存対応、再読込み整合性を確認。
未宣言modifier/constraint/animationは今回は拒否し、任意許可に緩めていない。
形状ごとの8頂点条件は共通Validatorに存在しない。

Skill Validatorでは既存cuboidの8頂点・6面、独立な角/寸法/面平面、外向き法線、
閉じたedge topology、材質接続等を検査する。幾何構築関数は期待値計算に流用しない。
cylinderは頂点/面数、半径、上下ring、角間隔、caps/側面、local boundsを検査する。
Recipe validatorはframeと子出力を検査し、共通契約が全子artifactの存在を保証する。
domain_validatorsの呼出し口はあるが、高度な建築/物理/domain判定は登録していない。

geometry digestは頂点と面を順次hash化し、inventoryに全頂点/面配列を保存しない。
structure_sha256はartifact ID、source/producer、role/type、geometry digest、変換、依存から算出。
材質/画像の同一性や物理妥当性を証明するhashではない。

実機で生成した円柱Artifactの抜粋（行列、他Artifact等は省略）:

```json
{
  "artifact_id": "a.f3a4528182d8554499ce420b963ba5b4ebc32571",
  "source_node_id": "column.side",
  "producer_node_id": "column.side",
  "role": "geometry",
  "local_role": "geometry",
  "type": "Mesh",
  "reference": {
    "object": "a.f3a4528182d8554499ce420b963ba5b4ebc32571",
    "mesh": "Cylinder"
  },
  "geometry_digest": "6f51461ed76a6c390a8a12410a5224f17008c4cb711f2998badf15a981013919",
  "vertex_count": 32,
  "face_count": 18
}
```

## 7. ビルド保存とQualityReport

新規buildはmanifest_version=2とし、従来のscene.blend / scene.json / result.json /
validation.json / blender.logに加えて以下を保存する。

```text
scene-v2.json             正規化したauthoring v2（元scene.jsonは保持）
resolved-scene.json       authoringと解決済みnodeの対応
plan.json                 BuildPlan
skills.lock.json          使用スキルの固定版/実装/依存hash
artifact-manifest.json    再読込みで検証した軽量生成物一覧
quality.json              段階別品質状態
build.json                staging/validated/failed、環境、主要10成果物のhash
reopen/                   別Blenderプロセスの再読込み検証記録
```

新規buildが全ての必須構造検証を通るまでlast_successful_buildを変更しない。
失敗例は独立保存し、quality.jsonに失敗した段階を記録する。
従来の4成果物hashだけを持つplan無しbuildも読込み、凍結したlegacy Validatorで再検証できる。
既存buildへplanを自動追加したり、blendを再保存したりしない。

QualityReport schema version 1はspecification / execution / structure / visual / domain /
export / target_compatibilityを分け、各々state・reason・evidenceを持つ。
stateはpassed / failed / not_run / not_applicable。
通常成功buildは最初の3段階だけpassedとし、残りはnot_run。
acceptanceは常にnot_evaluatedで、構造成功からacceptedへ格上げしない。
プレビュー生成や今回の目視確認も、自動visual評価のpassedとして記録しない。
accepted Revisionの運用はPhase 2Bの範囲。

## 8. プレビュー公開の修正とWorker protocol

### F10修正

operations/<attempt>/preview.pngを不変原本とし、build/preview.jsonが指すPNGを正本とする。
PNG全chunkのCRC、IHDR、IDAT、IEND、zlib stream、scanline数/長さ/filter、解像度を検査。
boundedな非interlace PNGを対象とし、ヘッダのみや途中切れは拒否する。
画像内容・写実性の検査とは分離している。

公開参照はschema_version=2、原本への相対path、SHA-256、resolution、render情報、attempt IDを持つ。
原本作成・完全性検査・他metadata書込み後、preview.jsonを一回のos.replaceで確定する。
参照更新でOSErrorが出たら旧preview.jsonと旧PNG原本はそのまま残る。
新しい未公開PNGは失敗操作の診断用として保持する。

v1 consumer向けに、最初のプレビューだけbuild/preview.pngへ互換snapshotを作る。
これは更新せず、以後の公開参照とも照合しない。native v2 buildでは作らない。
旧schemaのpreview記録を読む場合のみ、従来どおり旧copyのhashも検査する。
常に最新PNGを開く場合はstatusのpreview.pathまたはoperationsの出力を使う。

### JSON protocol 2

新Runnerは既知actionにprotocol_version=2、attempt_idを付ける。
plan操作にはplan_pathとplan_digestを渡す。
成功結果は同じprotocol/attempt/planと環境metadata、mesh件数、artifact件数、manifestを返す。
件数と配列、Mesh ID集合、manifestの計画対応が不整合なら拒否する。
例外結果はok=false、protocol、attempt、plan digest、action、error_type、error、tracebackを持つ。
クラッシュで結果が存在しない場合も終了コード/ログ/経過時間を記録して失敗にする。

旧workerを新protocol要求の実行先として黙って受け入れない。
旧result/buildの読込みはlegacyデータadapterで扱う。
現workerはplan無しv1の旧要求を互換処理できるが、v2生成にはBuildPlanが必要。
テストで明示した補助worker以外、manifestが任意scriptを選ぶ経路はない。

## 9. 操作と検証結果

```sh
uv sync --locked
uv run --locked scene-factory init example --schema-version 2
uv run --locked scene-factory compile example
uv run --locked scene-factory build example
uv run --locked scene-factory preview example --device cpu
uv run --locked scene-factory validate example
uv run --locked scene-factory status example
uv run --locked scene-factory skills list --query building
uv run --locked scene-factory skills show cylinder --version 1.0.0
uv run --locked scene-factory skills validate cylinder --contract-only
uv run --locked scene-factory migrate OLD.json NEW.json
```

新規スキルの試験・有効化例（実際のBlenderインストール先を指定）:

```sh
uv run --locked pytest -q tests/test_scene_v2.py tests/test_skill_registry.py \
  tests/test_artifact_protocol.py tests/test_preview_publication.py --junitxml=artifacts/unit-tests.xml
uv run --locked scene-factory skills validate cylinder --blender-path /path/to/blender \
  --activate --test-report artifacts/unit-tests.xml
```

実機の全回帰:

```sh
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -q --junitxml=artifacts/phase2a-final-tests.xml
uv lock --check
uv build --wheel
```

全回帰は**150 passed、failed=0、skip=0**（アプリ/単体132件、実Blender18件）。
既存62件のテストファイルは変更せず、新規契約/負例/CLI/実機試験を追加した。
別実行したPhase 0/1の回帰も**62 passed、failed=0、skip=0（8.62秒）**を確認した。
6組込みスキルは各々初期値と非初期値の2例で、生成・専用検証・保存後再読込みを通して有効化した。
主な試験は以下。

- v2未知フィールド/型/値/版/参照/親子循環/依存循環、v1移行と原本不変
- registry契約/entry point/依存cycle/候補拒否/証跡不一致、基本/新leaf/recipe登録と検索
- DAG/typed height/親world transform、Recipe展開、ID/seed挿入・並べ替え安定性、plan改変拒否
- artifactの欠落/追加/重複/role/型/件数/変換/参照、軽量inventory、QualityReport状態
- 実Blenderでv1とv2相当の構造一致、円柱、複合5出力、親子scale/回転、保存・再読込み
- 実Blendの欠落/追加/形状/parent改変拒否、名前だけ変更した場合のID維持、失敗時の成功版保護
- 旧形式plan無しbuildの読込み/validate/preview、原本blend不変
- PNG破損、生成失敗、公開参照のreplace故障、旧原本と前回公開参照の保護

E2E操作例はartifacts/phase2a-example、結果JSONはartifacts/phase2a-*.json、
最終試験ログはphase2a-final-tests.log / phase2a-final-tests.xml、旧62件の単独試験はphase2a-phase1-regression.logに保存。
新しい実機テストはartifacts/test-runs/phase2a-*、登録検証はartifacts/skill-validation/*に隔離する。
これらの生成物/ログはGitへ自動追加しない。公開するコード/manifest/evidenceはGit管理する。
E2Eのcompile→build→CPU preview→validate→Metal preview→statusとdoctorも成功。
最終コードでのbuild/preview/validate/status結果は各*-final.jsonに保存した。
3つのauthoring nodeが7つのresolved node/Artifact（6 Mesh＋1 Object）になり、
building.mainから5 Artifactを追跡できた。CPU/Metal PNGを開いて確認した。
wheelビルドと、Manifest/binding catalog/新skill/旧adapter/workerの同梱も確認した。

仕様例は[examples/v2/scene.json](../examples/v2/scene.json)、
[v1相当v2](../examples/v2-equivalent/scene.json)、旧[v1](../examples/minimal/scene.json)。
サンプルディレクトリ自体はinit済みprojectではない。

## 10. 受入と残課題

| 受入条件 | 結果・証拠 |
|---|---|
| 1–3: v1維持、v2、明示移行 | 旧62件、v1/v2形状一致、移行原本不変/上書き拒否、旧build再読込み |
| 4–6: Node/Artifact、複数出力、非直方体 | Recipeの5 Artifactと円柱32頂点/18面を実Blender検証 |
| 7–8: 共通/専用Validator | 新共通検証は形状非依存。cuboidに独立な角/面/寸法/法線/材質検査 |
| 9–11: 登録/検索/版固定/新leaf/Recipe | 6 Manifestを2例ずつ実機検証。candidate/disabled/不明entry/不正依存を拒否 |
| 12–14: plan/DAG/typed input/seed | plan保存、roofの高さ追従、親子変換、無関係node挿入/順序変更の安定性 |
| 15–16: Artifact/Quality契約 | source/producer/role/IDを照合。structure以外の品質をpassedにしない |
| 17: 公開失敗の保護 | PNG生成後のos.replace故障注入で旧参照/旧原本を保持 |
| 18: 実Blender | 非直方体、Recipe、改変拒否、再現性、旧build互換、成功版保護を確認 |
| 19–20: 回帰/未検証の明示 | 150件全成功。Ubuntu等は以下のとおり未検証として残す |

MacでのCLI生成・検証、CPU/Metal、旧データ互換、非直方体/複合スキル、
plan/pin/Artifact/Quality契約、F10修正をPhase 2Aの受入対象とする。
Ubuntu 24.04 x86_64は共通ソースと同じCPU試験を利用できる設計だが、
実機、CUDA/OptiXは未検証。VS Code GUI上の操作も未検証であり、
このCodexセッションからCLIを動かせたことと区別する。

自然言語・画像からの生成、SceneIntent、accepted Revision/完全rollback、
自動修復、cache/増分ビルド、災害/洞窟の本格生成器、PBR/assetライブラリ、
大規模性能、USD/Isaac Simは今回未実装。Domain Validatorの高度な実装もない。
最小スキルの成功はこれらの能力や写実性の証明ではない。

この共通契約を使ってPhase 2Bへ進める。次はIntent/参考根拠、意味的Revision、
品質profileと停止条件のある自動縦断を追加し、今回のcompiler/Runner/validatorを再利用する。
