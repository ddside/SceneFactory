# Phase 3D — 正常環境からの決定的な屋内損傷

アプリ0.7.0。Phase 3Cの正常SceneSpec・部材ID・Catalog・Workflowを維持し、
正常状態の検証後に登録済みの損傷Processorを適用する。物理的な崩壊過程、地震応答、
剛体、火災、浸水、粉塵、大量瓦礫、USD/Isaac Simは実装しない。

## データと処理境界

Source SceneSpec v2の正常nodes/appearance/interiorはそのまま保持する。
任意の`damage` v1と`damage.controller`ノードだけを追加し、新しいRevisionに保存する。
指定なしのSpecは従来の正常生成・検証経路を使う。

```json
{
  "schema_version": 1,
  "controller_node_id": "damage.controller",
  "operations": [{
    "operation_id": "shelf.topple",
    "target_node_id": "building.main.room.01.furniture.shelf.damage-demo",
    "damage_type": "object_topple",
    "severity": 0.5,
    "seed": 42,
    "displacement": [0, 0, 0],
    "rotation_degrees": [90, 0, 0],
    "pivot": [0, 0, 0],
    "support": {"kind": "floor", "ground": true},
    "parameters": {}
  }],
  "passage_expectations": {"building.main.room.02": "blocked"}
}
```

これは契約説明用の断片。上記の任意passage_expectationsは実在するSpaceと分類を要求し、
期待と異なる場合はFAILにする。操作先は展開後のnode IDで解決する。
`target_component_id`でRecipeの部材node、`target_role`でdoor leaf等のMesh roleを選べる。
Artifact IDはnode IDと別物であり、target_component_idに混用しない。

| damage_type | 状態 | 処理 |
|---|---|---|
| rigid_displacement | displaced | 平行移動・回転 |
| object_topple | tilted | 同じ剛体姿勢処理。X/Y回転と接地で傾斜・横倒し |
| component_detach | detached | 支持元から物理parentを解除し、部材を独立配置 |
| component_fracture | fractured | 矩形範囲で切断。残存部を元ID、分離部を独立破片にする |
| structural_damage | damaged | 局所領域をBoolean差分で実欠損にし、切取部を独立配置 |
| partial_collapse | collapsed | 同じ切取処理を床・天井等へ適用し、落下部を配置 |

`normal`はdamage指定がない元状態。操作リスト順が実行順で、同一Artifactへの複数操作は
矛盾を避けるため拒否する。1操作で形状変更と破片の移動・回転を組み合わせる。
親Recipeの操作とその部材操作も、対象集合が重なる場合は競合エラー。
存在しない対象・role・support、無効なregion/severity/seedは黙って修正しない。

severityは0.01..1。欠損regionは指定最大領域の各軸を中心から`0.35+0.65*severity`倍にし、
irregularityもseverity倍にする。破断位置は既定で`0.15+0.7*severity`、
parameters.split_fractionの明示値で上書き可能。移動/回転は明示のTransformを優先し、
severityで二重に増幅しない。parameters.axisは0/1/2、irregularityは0..0.2。

displacementと回転軸はワールド座標。pivotは対象node frame内の座標をワールドへ変換する。
region.minimum/maximumは対象Meshのローカル座標。geometry操作は1 Meshに限定する。
seedは不規則な凸切取領域の生成に使い、同じSpec/seed/versionで同じGeometryを再生成する。
床高さは建物のfloor基準から解決する。任意のsupport.node_idを指定する場合はfloor slabを要求する。
床への自動配置は実頂点の最低点を使い、浮遊や大きな埋没を避ける。安定姿勢の計算ではない。

## Skill・BuildPlan・Artifact

追加Skillは`damage_processor@1.0.0`の1つ。共通実装で6操作を扱い、不要に6個の
似たSkillへ分割しない。既存Registryに任意のreviewed postprocess bindingを追加し、
その実装・共通helperを証拠hashへ含める。candidateでは通常生成できない。
登録試験では6操作、複合C/D、床・梁・扉、PASS/WARNING接触の11 fixturesを実Blenderで保存・再読込する。

純粋compileは正常状態を既存契約で検査し、baseline_plan、解決済み操作、
決定的な破片Artifact宣言を凍結する。Blender生成やBooleanをcompileでは実行しない。
破片IDは元producer node + operation IDから導出し、severity変更でIDを変えない。
元ID・元Skill・source_node_id・部材lineage・MaterialRefを保持する。
Artifact.damageへoperation ID、original_artifact_id、状態、支持の保持/解除フラグを記録する。
fixedは支持元への保持意図であり、Isaac Simのstatic body設定や物理安定性の証明ではない。

Blenderは次の順に処理する。

1. 正常Planの生成、PBR適用、既存skill/interiorの実検証。
2. 対象Artifactを解決し、形状変更だけをprivate Meshへ分離。
3. 差分/切断と独立破片生成、姿勢変更、支持解除、最低点の床合わせ。
4. 同じMaterialRefのPBR/metric UVを適用し、損傷専用検証。
5. 新しいstagingへ保存し、再読込後にも検証。旧acceptedは変更しない。

BooleanはExact solverで一時Objectのコピーに適用し、元Mesh Datablockを編集しない。
残存・切取体積の和を元体積と照合し、空の残存部やゼロ体積破片を拒否する。
移動・転倒・脱落だけの場合、保存されるMeshを複製しない。未変更の共有関係も検査する。姿勢操作ではMeshをワールド姿勢で独立配置し、
元のRecipe frameは正常状態との対応用に保持する。現在姿勢の正本は各ArtifactのTransformとdamage操作である。

## 損傷後の検証

正常interior profileは変更しない。`damaged_interior`は正常baseline実検証、
損傷後の構造・PBR・交差検査と実画像Reviewを要求する。
正常時の直立、全部材接続、全通路開放を損傷状態に適用しない。

再読込検証では、別の一時Sceneで正常状態を再生成・既存Validatorで検証した後、
操作を決定的に再実行し、保存済み全ArtifactのGeometry digest、Transform、
parent、状態、lineage、Mesh共有関係と照合する。再生Sceneは後始末し、保存Sceneを変更しない。
形状を生成する処理との照合だけに頼らず、閉形状・正の体積・面積・法線方向の整合、
BVH候補からの非隣接三角形edge/face交差、床接地、保持した棚上内容物の支持も別途検査する。
正常部材の型固有Validatorは維持し、操作で意図的に変わる対象と関連ancestorだけを損傷検証へ委譲する。

PBR/UV/ref/hash検査を保持する。正常PBRの共面重複禁止は損傷にそのまま使わず、
実体積による接触評価へ置き換える。任意の複雑Meshに対する完全な破壊・自己交差保証はしない。
検証した対象は既存の矩形部材、押し出し壁、床・天井、柱/梁、扉。

### PASS / WARNING / FAIL

AABBは候補抽出のみ。凸形状は半空間クリッピング、それ以外は実MeshのExact Boolean intersectionを使い、
交差体積、対象の小さい方の体積との比、交差体の厚み、部材寸法、semantic、
支持意図を記録する。AABB重なりだけで重大FAILにしない。

一時的な計測Booleanが共面の微小面で開放形状になる場合は、保存Meshを変更せず、
実頂点の凸包による上限と、未変更furniture_partの検証済み内包直方体による下限を計算する。
内包体は各面からbevelの2倍だけ内側にあり、変更済みMeshや任意Assetへ推測で割り当てない。
上限でも軽微と証明できる場合だけPASS、下限でも重大と証明できる場合だけFAIL。
区間が判定境界を跨ぐ場合はWARNINGとし、計測法と不確実性を明記する。
記録のvolume_lower/volume_upperが等しければ単一測定値、異なれば保証区間で、
intersection_volume/relative_volumeは上限側の診断値。AABBの交差体積ではない。
これによりBooleanの数値的な計測失敗を、保存Meshの破損や重大貫通と混同しない。

- PASS：相対交差体積4%以下かつ、スケールから算出した絶対深さ許容内。
- 深さ許容は最短寸法の3.5%（意図した破片接触は8%）と、最短寸法と1mmの幾何平均の小さい方。
  1mmは検証feature scaleであり、ユーザー文面の「数cm」を固定閾値にしていない。
- FAIL：相対交差が通常40%、意図した破片接触55%、床埋没25%以上。ほぼ完全な重複もFAIL。
- その他はWARNING。床は有限厚スラブとの交差だけでなく、床面より下の実体積で埋没を評価する。
- 薄い壁の横断は、実Mesh交差が存在し両側へ跨る場合に、壁厚と断面から占有率を追加評価。
  横断断面の過半が壁で塞がる場合はFAIL。開口端で少し当たる部材を一律FAILにはしない。
- 元のfloor slab本体が歩行面の下に存在することを床埋没と誤判定しない。

これらは工学的安全基準ではなく、m単位の屋内生成に対する明示的な品質ポリシー。
PASS/WARNINGからRepairを起動しない。FAILはQualityを不適格にし、既存のbounded Repairへ渡す。
安全な定型修正がなければneeds_repairでCodexの修正を待ち、閾値を緩める自動ループは行わない。
修正後は全損傷を再検証し、別のFAILが出れば受理しない。

## 通路と自然言語編集

正常時と同じ部屋座標・2D占有・clearanceの考え方を使う。部屋入口から内部への到達と、
廊下入口から各部屋開口への接続を要求幅/半幅で測る。
passable / partially_blocked / blockedと、障害Artifact、位置、要求幅、判定条件を記録する。
廊下のpartially_blockedには、一部の接続先へ到達できない場合も含む。
これは保守的な配置近似であり、穴への落下危険、避難基準、ロボット動作、物理接触を保証しない。
明示した閉塞は正しい損傷表現であり、通常interiorの通行可能条件で拒否しない。

`damage_layout.normal_office/acceptance_scene/with_damage/operation`をCodexのauthoringに使える。
`clear_damage`は選択操作を取り除き、全解除ならdamage/controllerを削除して元の正常Specへ戻す。
全解除時はinterior profileを明示選択する。新しいLLM API、MCP、チャットUIは追加しない。

```sh
uv run --locked python examples/damage/create_proposals.py artifacts/damage-inputs
uv run --locked scene-factory generate artifacts/disaster-office --proposal artifacts/damage-inputs/normal.json
# 実画像を確認して既存reviewを提出した後:
uv run --locked scene-factory edit artifacts/disaster-office --proposal artifacts/damage-inputs/D.json
# 同じくDの実画像確認・review後:
uv run --locked scene-factory edit artifacts/disaster-office --proposal artifacts/damage-inputs/E.json
```

## 実施結果

最終全回帰は **428 passed / 4 skipped**（416.66秒）。既存383件を保持し、
新規26純粋試験と19実Blender試験を追加した。実Blender回帰は計69件。
4 skippedは未変更Providerのopt-inライブAPIで、今回の成功件数へ含めない。
`artifacts/phase3d-regression.xml`に全結果を保存した。
登録では11 fixtures×生成/再読込の22実プロセスを別枠で実施した。
既存asset_instanceのPBR検証binding証拠も更新した。新しいProviderや依存は追加していない。

| Scene | 結果 |
|---|---|
| A | 棚転倒、椅子2脚の移動・傾斜。GeometryとMesh共有を維持し、damaged_interior受理 |
| B | 棚板・扉の脱落、椅子脚1本の破断。1独立破片、対象Meshのみ分離。他の部材を維持。受理 |
| C | 不規則な壁欠損、天井崩落、柱局所欠損。3独立破片。閉形状・体積・再読込検査を通過し受理 |
| D | 棚転倒・棚板脱落・壁欠損・天井落下を合成。会議室入口blocked、廊下partially_blocked。WARNING 3件を不要に修正せず受理 |
| E | 棚を正常姿勢へ復元し、天井region/severityを縮小。会議室partially_blocked、廊下passableへ変化し受理 |
| F | 同じ形状の3組でPASS/WARNING/FAILを確認。重大ケースを含むAttemptは期待どおり不受理・Repair待ち |

Fの公称X重なり量は幅の1%/15%/80%。実形状は面取りがあるため体積比と同一ではない。
最終測定はそれぞれ交差体積の保証区間約[0.002847,0.004797]、[0.069265,0.071997]、
[0.377635,0.383996] m³となり、PASS/WARNING/FAILを証明できた。
別途、1/4寸法の実Blender生成・再読込でも3段階を確認した。
実体が離れた斜め部材でAABBだけ重なるケースはFAILにしていない。
PASS/WARNINGは1 AttemptでReview待ちへ進み、Repairを起動しないことを実試験した。
FAIL修正で別の重大交差を作った場合も受理せず、2 Attempt上限後の3回目を拒否した。

A〜Eは正常基準に対する非対象ArtifactのGeometry digestを照合した。
Aは267 Mesh Object / 62使用Mesh Datablockで正常版と同じ共有を保持。
Bは268 / 64で、破断元の私有Meshと独立破片の2つだけが増えた。
D/Eの共通331 Artifactのうち、Geometryが変わったのは天井本体と対応破片の2つだけ。
棚は元の共有・階層・姿勢へ復元し、他の損傷・MaterialRef・ID/seedを維持した。
D→E→正常基準→EのRollbackを再生成なしで往復し、旧acceptedの全bundle hashを検証した。
最終的な公開先はE。証拠は`edit-rollback-evidence.json`に保持する。

補完として、Desk天板の部分欠損・独立破片も実Blender保存・再読込に成功した。
床欠損、梁破断、扉leaf脱落は登録fixtureと実Blender回帰で検証した。
机天板と1/4寸法の補完確認はpytest件数へ重複加算していない。

### 実画像

A〜Fのoverview/top/interior 18枚と、正常基準3枚を実閲覧した。
全体画像で判読しにくいBの脚破断とCの壁穴だけ、512px近接画像2枚を追加確認した。
最終確認セットは計23枚。各AttemptのVisualReviewは元の3画像のpath/hashに固定される。
診断画像は`B-detail-perspective.png`と`C-detail-perspective.png`。
天井/屋根を隠した断面画像だけで天井穴を証明せず、実Geometry・切取体積で補完した。
写実性、物理安定性、構造耐力は評価していない。

初期のC/Dで三角形境界接触を自己交差と誤判定したため、面内部の横断だけを検出するよう修正した。
接触境界Fで計測Booleanの開放面も発見し、上記の幾何保証区間を実装して再試験した。
保存される損傷Meshの閉形状条件を緩めたり、交差ゼロへ繰り返し配置修正したりはしていない。

### 性能

macOS / Apple M5、Blender 4.5.15 LTS、Cycles CPU、384px、16 samples、denoise。
アプリPython 3.12.13 / uv 0.11.26、Blender Python 3.11.15。
一部は回帰と並行した実測で、単独の厳密ベンチマークではない。
Buildはworker内の正常生成・損傷・検証・保存、Previewは再読込/再生検証込みの3 worker合計。
アプリ側起動待ち・compile等の全時間ではない。RSSはbuild workerのpeak。

| Scene | Build秒 | Preview計秒 | Mesh Object / 使用Datablock | 頂点 | 面 | 独立破片 | peak MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 5.516 | 23.009 | 267 / 62 | 8192 | 7670 | 0 | 252.0 |
| B | 5.073 | 18.858 | 268 / 64 | 8216 | 7684 | 1 | 269.8 |
| C | 4.854 | 17.779 | 270 / 65 | 8276 | 7718 | 3 | 286.5 |
| D | 5.934 | 23.466 | 270 / 65 | 8276 | 7718 | 3 | 227.1 |
| E | 5.900 | 21.214 | 270 / 65 | 8276 | 7718 | 3 | 281.2 |
| F | 1.012 | 4.008 | 19 / 15 | 416 | 386 | 0 | 212.8 |

頂点/面はObjectごとの合計。使用DatablockはObjectが参照する一意Meshの数。
破片は新規Artifactを数え、元IDで保持した残存部は加算しない。
再生検証は通常生成よりコストがかかるが、別キャッシュや複雑な永続化機構は導入していない。
`performance.json`にbuild IDとの対応を保存した。

### 実行した主なコマンド

```sh
uv sync --locked
uv run --locked pytest tests/test_damage.py -q --junitxml=artifacts/phase3d-unit-final.xml
uv run --locked scene-factory skills validate damage_processor --activate --test-report artifacts/phase3d-unit-final.xml
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -q --junitxml=artifacts/phase3d-regression.xml
```

BlenderのパスはこのMacの実行記録で、アプリに固定したPythonパスではない。
実Blenderはsandbox起動制限のため許可済み制限外CLIで実行した。
このセッションでは必要に応じ`UV_CACHE_DIR=.uv-cache`を使った。
例外・異常系のログ、旧失敗Attempt、正常/損傷の受理bundleも削除せず保存している。

必須受入A〜Fを満たした。Phase 3Eへは幾何・ID・支持・正常/損傷の対応を維持して移行可能。
ただし、下記の未実装・未検証項目は引き続き別受入が必要。
生成データ・画像・ログ・JUnitはignored artifacts配下、入力生成コードと登録証拠ManifestはGit管理。

## 残る範囲

macOSのBlender 4.5 LTS / Python 3.11と、uvのアプリPython 3.12で検証する。
Ubuntu 24.04、CUDA/OptiX、USD/Isaac Simは別の実機・出力受入が必要。
火災/浸水/粉塵/大量瓦礫、剛体、構造力学、FEA、LOD、増分キャッシュは実装しない。
支持rayと交差ポリシーは物理的な安定姿勢・荷重支持を証明しない。
形状・支持・正常/損傷の対応を維持する基盤としてPhase 3Eへ接続する。
