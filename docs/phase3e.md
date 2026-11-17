# Phase 3E — 災害固有の瓦礫・痕跡・表面劣化

アプリ0.8.0、Phase 3Dの`f3fc0d4`を基準とする。正常環境、damage v1、Recipe、
Catalog、Revision/acceptedの境界を維持する。動的災害、剛体・熱流体・燃焼計算、
ロボット通行性、Collision Mesh、USD/Isaac Sim統合は実装しない。

## Effect契約と実行

SceneSpec v2に任意の`effects` v1を追加する。正常nodesと既存damageを上書きしない。
`effect_layout`はCodex向けの入力作成helperであり、自然言語parserや別agentではない。

```json
{
  "schema_version": 1,
  "controller_node_id": "effects.controller",
  "items": [{
    "effect_id": "quake.concrete",
    "disaster_type": "earthquake",
    "effect_type": "debris",
    "target_node_id": "building.main.wall.north",
    "source_operation_id": "wall.hole",
    "region": {"room_id": "building.main.room.02", "minimum": [-2.65,3.5,0], "maximum": [2.65,5.75,0.8]},
    "severity": 0.7,
    "seed": 42,
    "material": "effect.concrete",
    "parameters": {
      "fragment_count": 16, "density": 1,
      "size_min": [0.08,0.06,0.04], "size_max": [0.2,0.14,0.1],
      "extent": [2,2,1], "direction": [1,0,0],
      "distribution": "source_based", "material_type": "concrete",
      "irregularity": 0.25, "variants": 4, "volume_budget": 0.5,
      "existing_ids": [], "scatter_skill": "product_package"
    }
  }]
}
```

断片例。完全な入力は`examples/effects/create_proposals.py`で新規ディレクトリへ生成する。
materialはappearance.materials内の不変MaterialRef alias。region/heightはroomのm座標。
Effect ID、scene/effect seed、index別streamで形状と配置を決定する。個数は
`floor(fragment_count*density+0.5)`。減数時も残るindexのID・形状は維持する。
severityは表面濃度とGeometry crackの既存Damage強度へ作用する。明示個数・寸法を
暗黙に二重減衰しない。寸法・密度・extent・MaterialRefは別パラメータで制御する。

`effect_type`はdebris / scatter / surface / crack_geometry。
Geometry crackは既存structural_damageへ派生し、実切断部をsynthetic=falseとして扱う。
細い亀裂はfine_crackの方向付きWave/Noise Shaderであり、形状欠損とは別物。
source_operation_idがあれば実在する損傷操作と対象の一致を要求する。
追加瓦礫はsynthetic=true、因果sourceと実切取fragmentを区別する。明示体積上限に加え、
切取体積の半分を追加syntheticの上限とし、同一source合計も検査する。質量保存の物理モデルではない。
操作なしのsourceは領域体積の20%を上限とする。

純粋compileはbaseline Plan、追加node/Artifact、Material bindings、適用順を固定する。
Blenderは正常基準→既存damage→瓦礫/散乱→表面layerの順に実行する。
同じlayer番号・重なる領域・同じMeshの表面競合を拒否し、明示layerとeffect_idで順序を固定する。
同一sceneへの二重適用はmarkerで拒否する。編集・解除は毎回前効果baselineから適用する。

## 再利用Skillと形状

- `debris_fragment@1.0.0`: 閉じた低ポリ凸形状。concreteは不均一角形、plasterは薄板、
  woodは細長い楔、glassは薄い三〜五角板、genericは五角系の不均一塊。
- `disaster_processor@1.0.0`: 共通後処理。既存Registry/postprocess bindingを使う。
- 箱・商品・モニターの散乱は既存product_package/storage_box/monitor Recipeを再利用する。
  existing_idsの既存小物はID・Mesh共有・MaterialRefを保って移動する。

形状・appearanceが一致するprototypeはMesh Datablockを共有する。variantsは1..8。
大きさは各indexではなくprototype streamで決め、同じprototypeの再利用を可能にする。
薄板・ガラスの厚さ比、木材の長辺比、独立した寸法・閉形状・正の体積・面積・法線を検査する。
単体破片は最大24頂点/44面。Effect最大32、各count最大200、合計600、展開node最大1000。
寸法0.003..2m、extent最大20m、領域は実在room内。過剰入力は生成前に拒否する。

## 分布と接地

uniformは領域一様、clusteredは領域中心の分布、source_basedは実損傷位置または対象物中心、
directionalはsource分布に指定XY方向の偏りを加える。いずれも領域内へ制限する。
sourceが境界外にある場合は領域へ投影する。これは物理移流ではない。
矩形boundsと回転後の余白を使い、実頂点・面中心から実Meshへの下向きrayで支持高さを決める。頂点だけでなく実際の面中心・辺中点も使い、
面内部に載る薄片と積み重なりを扱う。
床・既存物・先に生成した瓦礫を支持候補にし、最大8個の決定的な配置候補から高さ予算内の位置を選ぶ。
小交差を消す反復repairではなく、支持面に載せる有限生成である。任意の安定姿勢や摩擦は保証しない。
近接支持、実頂点の領域、指定count、実体積、source分布、因果metadataを別途検証する。
支持境界でrayが外れる場合や面内部への接触も双方向の実表面最近接距離で確認し、破片高さの10%を3〜10mmへ制限した
概ねの接地許容を使う。これは接触のPASS/WARNING/FAIL閾値とは別で、物理安定性ではない。

settle_fraction(0..0.8)は破片高さに対する支持への沈み込み量。主にFのポリシー試験用。
通常は0。深い埋没を許可する抜け道ではなく、保存後の接触判定でFAILになる。

## 火災・浸水・Material分離

既存PBR graphを保持し、Object Material slotだけを分離する。共有Meshに対して
別Objectの表面を汚さない。Catalog MaterialRef・出典は保持し、layer材質refもPlanと検証結果へ残す。
今回の追加色・roughnessは自作の手続き材質で、外部テクスチャの無断取得はない。

火災はsource中心の局所falloff、上方に偏るsoot、不均一なscorch/char/heat discoloration、
焼損木片Geometryを組み合わせる。浸水は指定高さのwaterline、下部のmud/wet Shader、
厚いmud Geometry、方向性の木片・箱を組み合わせる。wetはroughnessを下げる。
Noiseはseed付き4D、room座標で領域maskを作る。別室はmask外となり、対象Meshの選択も明示する。
水位・幅・seed・座標参照・mask・色・roughnessと保存後graphを独立検証する。
火災の時間発展、煤の実付着量、流体、残留水面、光学・物理精度は保証しない。

## 品質・保存・編集

新しい`disaster_interior`は正常baseline検証、実Effect/solid/PBR/contact検証と実画像reviewを要求する。
既存interior、damaged_interiorの意味は変えない。AABBは候補抽出のみ。
Phase 3Dの実交差量/相対量と絶対深さの許容を継承し、PASSは維持、WARNINGは記録、
FAILだけが既存の予算付きRepair対象。保存Meshの不正は接触許容とは別に厳格拒否する。
小物の浮遊/支持と、剛体安定性・ロボット通行性を混同しない。
小さい世界座標Meshではfloat32座標誤差を測定の凸判定許容へ含める。Meshや接触分類閾値は緩めない。

baselineを`base-scene.blend`と`base-state.json`へ保存し、完全baseline Plan digestとファイルhashを
凍結する。Effectのみ変更した同じprojectは検証済みbaselineをロードして再利用する。
正常/損傷基準のSpec、Skill、Materialや実装変更はkeyを無効化する。新stagingで作成し、
旧validated/acceptedを上書きしない。新旧両cacheもbundle hashの保護対象にする。
保存後は別の一時Sceneで独立再生成し、全Geometry digest、姿勢、共有、ID、支持、Shaderを照合する。
再生成は検証のためであり、build段階のbaseline reuseとは区別する。
完全な依存DAG別の増分更新や大規模LODは未実装。
今回のcache再利用は同じBlender実バージョンで検証した。別patch/別OSへcacheを持ち越す互換性は未検証。

Effectの削除は新Revisionのitemsから除く。全解除時はeffectsとeffects.controllerを除き、
元のdamageまたはinterior profileへ戻す。既存damageの解除は独立操作。
Rollbackはaccepted bundleの切替で再生成しない。

## 受入・試験記録

最終Skill登録の正本は各manifestのvalidation_evidenceと
`artifacts/phase3e-disaster-activation-final.json`とする。追加2 Skillはvalidated。
debris_fragmentは5材質の生成/再読込、disaster_processorはA〜Dと実Geometry亀裂の5 fixtures。
既存asset_instance(1 fixture)、damage_processor(11 fixtures)も変更helperに対する証拠を更新した。
全5災害fixturesのdomainがpassedであることを実結果でも確認した。

関連単体116件、追加の実Blender統合15件が成功。統合試験にはキャッシュ編集、再現性/共有、
PASS/WARNINGでRepairなし、FAIL未受理、保存後のゼロ体積・法線・埋没・領域外・重複・
Shader水位・未変更部材・seed改変、二重適用、失敗時の成功版保護、cache hash破損拒否を含む。
異常なID/Region/MaterialRef、density/extent/severity/count、候補Skill、layer競合、
source操作、資源上限とEffect解除の純粋契約も検査する。
全482件を実行し、初回は477 passed / 1 failed / 4 skipped（487.97秒）。
失敗はSkill一覧の期待値に新2 Skillが未追加だった1件のみで、期待集合を拡張後、関連Registry
21件を再実行して全成功した。実装は変更していない。最終の各case確認結果は478成功・
未解決失敗0・4 skip（opt-in live Poly Haven）。全体を再実行した成功結果と偽らず、
全回帰XMLと修正後のRegistry XMLを別々に保持する。
実Blenderを使う84 test casesは全成功（今回追加15、既存69）。
証拠はartifacts/phase3e-regression.xml/.log、phase3e-registry-final.xml、
phase3e-integration.xml、phase3e-verification-summary.json。
live Provider試験はProviderコード未変更のため今回再実行しない。

受入ルートは`artifacts/phase3e-acceptance/`。A〜Dはそれぞれのproject、EはAの新Revision。
A〜Eの全3方向を実閲覧してimage/hash付きVisualReviewを記録しacceptedにした。
Fの3方向も実閲覧したが、重大FAILを含むためacceptedにしていない。

| Scene | 結果 | 内容 |
|---|---|---|
| A | accepted | 壁/天井の実損傷、concrete/plaster/glass、棚転倒と箱散乱、入口閉塞 |
| B | accepted | 店舗バックヤードの壁/天井soot、局所char/scorch、熱変色、焼損木片、家具部材脱落 |
| C | accepted | 住宅の1m水位痕、mud/wet、厚い泥、方向性の木片/箱、既存商品散乱と椅子移動 |
| D | accepted | 3部屋へ地震・火災・浸水Effectを分けた機能合成。現実の同時災害を主張しない |
| E | accepted | 瓦礫44→22、壁際集積。箱4は保持、棚転倒・正常/損傷Geometry・参照を維持 |
| F | 期待どおり未受理 | 8/6/4片の3群、沈み込み.01/.15/.6。PASS14・WARNING11・FAIL8、1 Attemptで停止 |

A〜EのWARNINGはそれぞれ6/0/2/5/4件。重大FAILなし、警告だけでRepairしない。
Fは`needs_repair`、Presentationは`candidate_not_accepted`。PASS/WARNING群だけの個別Workflowは
統合試験で`awaiting_visual_review`となり、余計なAttempt/Repairを起動しない。
接触件数は床/壁/物体ペアを含み、破片数とは異なる。

Eは前効果baselineを実再利用し、共通366 Artifactの全Geometry digest、MaterialRef、
正常/損傷ArtifactのTransformを維持。新Revisionのroot差分はeffectsのみ。
A→E→A→EのRollback往復と旧accepted両bundleのhash検査が成功。
Phase 3Dの既存A〜D accepted bundleも読み取り検査で破損なし。
証拠は`edit-rollback-evidence.json`と各`*-accepted.json`。
全Effect解除の実Blender E2Eも別projectで実施し、元の正常/損傷331 ArtifactのID集合、
Geometry digest、Transformを復元した。旧acceptedは不変。
証拠: artifacts/phase3e-remove-gw_r4a0a/project/evidence.json。
純粋Spec検査を通るが配置高さを満たせない入力を、acceptedを複製した隔離projectへ適用する
実Blender途中失敗試験も実施。baseline読込後の配置で失敗し、新bundleを公開せず旧acceptedを保護した。
証拠: artifacts/phase3e-failure-_r03sdds/evidence.json。

画像閲覧ではAの損傷元近傍の集積・倒れた棚、Cの水平水位痕と泥/湿潤色、Dの部屋別表面、
Eの壁際への移動を確認した。Bは通常384px画像だけでは局所痕が小さいため、同じ保存buildの
`B-fire-closeup.png`(768px/32 samples)も実閲覧し、局所的な不均一煤・黒化収納・焼損木片を確認した。
close-upは保存.blendを変更せず、由来をB-closeup-source.jsonへ記録した。
天井はcutawayで非表示になるため、sootの天井対象・範囲は保存Shaderの実検査で補完する。
微小接触・水位寸法・細片数は画像だけで証明しない。明白な浮遊や重複はA〜E画像では認めなかった。
Fの深い埋没は画像だけで判断せず、測定FAILを採用した。

閲覧した正本画像は各`A/B/C/D/F-context.json`と`E-context.json`の
build_attempts[-1].previewsにあるOverview/Top/Interior合計18枚。Eの実体はA/operations配下。
A〜Eの不変reviewはproject/visual-reviews配下。FはF-image-inspection.jsonへ診断記録を残す。

### 性能

macOS、Cycles CPU、384px/16 samples/denoise。Buildはworker生成+実検証、Previewは
3回のworker実行（再検証を含む）の合計秒。アプリcompile・別reopen・公開を含む総時間とは別。
Material列は保存シーンの実Object slotにある使用材質数。既存workerのdata slot統計だけでは
BのObject overrideを数え切れないため、actual-scene-metrics.jsonで独立再計測した。
下表の頂点/面はworkerのObject展開合計。テクスチャは本受入fixtureでは0。

| Scene | Build秒 | Preview秒 | Mesh Object / data | 頂点 / 面 | 追加片数 | Material | peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 7.51 | 26.10 | 322 / 85 | 8960 / 8638 | 48 | 85 | 296.3 |
| B | 3.39 | 12.05 | 127 / 48 | 3596 / 3398 | 8 | 58 | 276.2 |
| C | 2.20 | 8.23 | 87 / 49 | 2128 / 2098 | 24 | 49 | 255.2 |
| D | 8.04 | 29.33 | 326 / 97 | 9124 / 8710 | 48 | 97 | 331.8 |
| E | 5.43 | 24.83 | 300 / 85 | 8746 / 8298 | 26 | 85 | 300.9 |
| F | 0.82 | 3.74 | 31 / 25 | 368 / 422 | 18 | 25 | 226.4 |

追加片数にはscatter Recipeのrootを含む。Eの瓦礫半減は44→22、箱4を含む追加root全体は48→26。
形状variantと有効appearanceが一致するものだけを共有する。表面layerはObject slotなので共有Meshを増やさない。

共有後の実頂点/面はA 2082/1980、B 1164/1100、C 1192/1158、D 2364/2256、
E 2082/1980、F 320/350。生成物・基準・検証ログはperformance.jsonとactual-scene-metrics.jsonへ保存。

独立の瓦礫増数試験は`artifacts/phase3e-performance-9xy01b5l/metrics.json`。
同じ部屋・4 prototypes・同じ材質・高さ上限で、順番に実行して他のBlender試験と重ねていない。

| 片数 | worker秒 | compile/build/reopen総秒 | Mesh Object / data | peak RSS MiB |
|---|---:|---:|---:|---:|
| 16 | 0.79 | 2.97 | 29 / 17 | 225.3 |
| 64 | 1.13 | 3.35 | 77 / 17 | 232.0 |
| 128 | 1.65 | 4.59 | 141 / 17 | 239.9 |

すべてdomain passed。16→128個で共有data数17を維持。小〜中規模の実測であり、
600片上限や大規模環境・任意形状の性能保証ではない。

### 再実行コマンド

```sh
uv sync --locked
uv run --locked python examples/effects/create_proposals.py artifacts/effect-proposals-new
uv run --locked scene-factory generate artifacts/effect-A-new --proposal artifacts/effect-proposals-new/A.json
uv run --locked pytest tests/test_effects.py tests/test_damage.py tests/test_library.py --junitxml=artifacts/effect-units-new.xml
SCENE_FACTORY_TEST_BLENDER=/path/to/blender uv run --locked pytest tests/test_effects_integration.py
BLENDER_EXECUTABLE=/path/to/blender SCENE_FACTORY_TEST_BLENDER=/path/to/blender uv run --locked pytest -q
```

macOSの今回の実行パスは`/Applications/Blender.app/Contents/MacOS/Blender`。
コードには埋め込まず、環境変数/CLIで選ぶ。Blenderのsandbox起動制限があるため、
実Blender試験は承認された制限外プロセスで実行した。uv/Python分離・依存は変更していない。


## 制限と次段階

macOS Apple Silicon / Blender 4.5 LTS / app Python 3.12 / Blender Python 3.11を使用。
Ubuntu 24.04実機、CUDA/OptiX、USDの効果shader変換、Isaac Sim読込は未検証。
保存するm単位、ID、Transform、Geometry、MaterialRef、damage/effect、lineage、support、
semantic、fixed、detail/obstacleは将来exportの入力であり、今回の物性/Collision設定ではない。
細片は低ポリの合成形状で、任意材質の破壊再現ではない。画像は静的で、写実性を受入条件にしない。
Phase 3Fでは、このmetadataを保持したexport/Collision分離等の独立受入を計画できる。
