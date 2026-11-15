# Phase 3A — モジュラー建築物と室内構造

アプリ0.4.0。macOS Apple Silicon / Apple M5、uv 0.11.26、アプリPython 3.12.13、
Blender 4.5.15 LTS / 内蔵Python 3.11.15で検証。Ubuntu、CUDA、OptiXは今回未検証。
目的は小規模な矩形・直交建築の幾何的成立であり、写実性や構造安全性ではない。

## 追加スキル

全てversion 1.0.0。candidateから単体テスト、実Blender生成・保存・再読込を経て
validatedへ登録する。正確なpin、テスト名、hash、実測値は各SkillManifestの
validation_evidenceに保存する。

| Skill | 種別・成果物 | 責務 |
| --- | --- | --- |
| arch_wall | leaf / Mesh | 厚い壁、0〜4個の矩形開口、外壁/間仕切/廊下境界の区別 |
| arch_opening | leaf / Empty | 壁slotに対応する独立ID、寸法、種別、位置、WallRef |
| arch_door | leaf / frame Mesh + leaf Mesh | 開口に合う3辺枠、ヒンジ位置と開き角の扉 |
| arch_window | leaf / frame Mesh + glass Mesh | 4辺枠、薄い簡易ガラス部材 |
| arch_slab | leaf / Mesh | purpose=1床、2天井、3屋根。厚みのある独立部材 |
| arch_space | leaf / Empty | 寸法を持つ論理的自由空間のmarker |
| arch_room | Recipe / frame + volume child | 部屋ID、寸法、出入口、廊下への参照 |
| arch_corridor | Recipe / frame + volume child | 廊下ID、寸法、外部入口への参照 |
| arch_building | Recipe / frame + 床・天井・屋根child | 建物寸法、外周・室内・接続・部材関係の検証 |

既存building_recipe@1.0.0など6スキルの意味・版・証跡は変更しない。
新旧を暗黙に置換しない。旧solidを室内モデルへ移す際は、新しいarch_buildingと
明示的な部材Specを新Revisionで作り、旧acceptedを保持する。

## データモデルと入力

SceneSpec v2 / SkillManifest schema 1 / BuildPlan schema 1 / ArtifactManifest /
QualityReport schema 2 / protocol 2を継続利用する。新しい別正本は作らない。

`architecture_layout.building_scene(width, depth, height, rooms, thickness)`は
通常の編集可能なSceneSpecを返す純粋関数。自然言語パーサーではなく、Codexが
選択して使う小さなレイアウト構築器である。入力例はexamples/architecture配下。
1部屋は廊下なし、2〜3部屋は南側に幅1.6mの廊下、北側に並ぶ部屋と各室の窓。
玄関は南側、各室のドアは廊下境界の壁に設ける。

width/depthは外周寸法、heightは床上面から天井下面までの有効高さ。
壁厚は内側に取る。床はZ=-floor_thickness〜0、壁は0〜height、天井はheightから、
屋根は天井上面から積む。したがって高さ3mの例の屋根上面は3.3m。
単一部屋8×6m・壁厚0.2mの内寸は7.6×5.6m、有効高さ3m。
床・天井・屋根は建物全体の独立した連続slabであり、各部屋で分割した床ではない。

建物の主要部材は全て明示的な著作ノード。Recipeの中へ壁・開口・間取りを隠さない。
床等の固定childとspace markerだけをRecipe展開する。各壁にはwall_kind/side、
各slabにはpurposeがあり、将来の部材置換・損傷対象を個別に識別できる。
接続はroom → access OpeningRef → wall、room → corridor SpaceRef、
corridor → entrance OpeningRef → 外周wallとして永続化する。
建築スキルのframeとmeshは既存のstable_id、producer/source ID、seed、parent、
role、ArtifactManifestのdependenciesとplanにより追跡できる。

## 型と最小限の契約拡張

従来のLength→elevation入力は維持する。以下の型付き参照を追加した。

| 型 | 出力値（producerのローカル寸法） | 入力target |
| --- | --- | --- |
| WallRef | [length, thickness, height] | reference |
| OpeningRef | [width, depth, height] | reference |
| SpaceRef | [width, depth, height] | reference |

参照のidentityはbinding.node_idで、寸法vectorだけでは同一視しない。
reference入力は変換を暗黙変更せず、依存DAGへproducerを加える。
壁・開口・建具の実際の親、local位置、型、寸法、slot対応をskill contractで検査する。
WallRefは任意のMeshへの未検証ポインタではなく、arch_wallの出力である。

Manifestに任意のcontractとtest_scenesを追加。contractはentrypoints.jsonで許可した
bpy非依存のarchitecture_contracts関数のみ。純粋compileの解決後に汎用dispatchし、
新形状の分岐を中央validatorへ増やさない。実装・validator・contract・supportのhashを
pinへ含める。test_scenesは必須参照を持つスキルの完全な登録試験fixtureであり、
通常生成でcandidateを許可する抜け道ではない。
AST検査は正確なソースbytesをキーに限定cacheする。現在のファイルhash検査は省かない。

## 壁・開口・建具の幾何

Booleanや黒い矩形の貼付けを使わない。壁の長さ/高さ方向を開口境界で分割し、
空洞を除いたセルの境界だけを厚み方向へ押し出す。セル間の内部面を出さず、
共有頂点を統合した閉じた壁ソリッドを作る。窓には4辺、床からのドアには3辺の
revealが実在する。壁の端や上端を欠損させる開口、開口同士の重なり/接触を拒否する。

壁はopening_countと固定slot1〜4の数値パラメータを持つ。各slotにwidth/height/
sill/offset/kind（1ドア/2窓）を置く。独立arch_openingノードが同じslotを参照し、
重複・不一致を検出する。未使用slotは開口を作らない。
この明示的な二者の対応はcompileで検証し、矛盾を黙って補正しない。

壁のmaterial_slot=0〜3は簡易色の選択で、外部材質・PBRではない。
窓glassは薄い青色の不透明な簡易Mesh。透過・屈折の再現はPhase 3Bへ延期。
扉は枠とleafを分け、既定90度の開き角を頂点へ反映する。アニメーションはない。
枠同士/床/壁との意図した接触を、不正な正体積の交差と区別する。

## 独立検証と品質受理

pure contractは開口の範囲/重なり、親子・typed reference・寸法対応、4外壁の閉じた
矩形外周、壁厚/高さ、直交壁の不要な重なり、床/天井/屋根、部屋の内包/非重複、
自由空間と壁の非交差、面積による未割当空間、出入口の両側の幾何的な接続を検査。
各部屋が廊下へ、廊下が外部へつながることを確認する。建物は移動/Z回転、単位scale。
任意の平面図、任意のpitch/roll/scaleの建築レイアウトは対象外。

Blender skill validatorは生成関数を再利用して合否を作らない。
実Meshのbounds、manifold/辺の向き、退化面/重複面、符号付き体積、壁面法線と
実体の内外を検査。開口中心・辺付近の複数の貫通rayが壁に当たらないこと、
側面/header/sillへのrayが正しい距離で当たることを検査する。
建具の外寸、枠の中心の空洞、扉のヒンジ変換、ガラスの厚み/位置も実測する。
保存後の再読込みでも同じ検証と構造fingerprintを照合する。
これは有限の解析的形状とsample rayの検証であり、任意のMeshの完全な衝突証明ではない。

architectural profile 1.0.0はspecification/execution/structure/visual/domainを必須とする。
domainには再読込後の全arch_buildingの実検証結果が必要。欠けた結果はnot_runで受理不可。
共通validatorはskillから返るdomain reportを収集するだけで、建築分岐を持たない。
basic_sceneの既存の限定的なdomain判定を建築保証に読み替えない。
構造安全、建築法規、避難計画、物理、写実性を保証しない。

## 非破壊プレビューと自然言語編集

architecturalでは3視点を生成する。

1. overview: 天井/屋根を残す外観斜視。
2. top: coverグループ（天井/屋根）だけを一時非表示。
3. interior: coverと南外壁を一時非表示にした室内斜視。

preview専用のhide_renderをfinallyで戻し、元の.blend・幾何を変更/保存しない。
既存の不変operation PNG、hash付きreview、QualityReport、accepted公開を再利用する。
3枚とも実際に閲覧するまでvisualをpassedにしない。

自然言語例はthree-rooms-request.jsonのraw_request。
Codexが`skills list/show`でスキルを選び、layout関数または明示Specを作り、
SceneIntent→compile→build/reopen→3画像→実review→acceptedを実行する。
「2番目の部屋の窓を大きく」ではresumeから対象room/window/opening/wallを特定し、
`enlarge_window(spec, 'building.main.window.room02', 1.8, 1.4)`で3ノードだけを更新する。
無関係なID、scene seed、全ノードの派生seed、既存artifact IDを保持。
全シーン再ビルドだが、新Revision/Attemptで旧acceptedを破壊しない。

## 検証結果

最終テスト件数・実行時間は以下の最終検証ログに記録する。

```sh
uv run --locked pytest -q tests/test_architecture.py --junitxml=artifacts/phase3a-unit-final.xml
# 上の成功XMLを登録検証へ渡す。各新Skillに同じ操作を実行。
uv run --locked scene-factory skills validate arch_wall --activate --test-report artifacts/phase3a-unit-final.xml
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -q --junitxml=artifacts/phase3a-tests-final.xml
```

Blenderはサンドボックス制限外の承認済みCLI実行。内蔵Pythonを変更していない。
既存197件と新規単体40件/実Blender8件が対象。登録fixture試験はpytestとは別に各Skillで
生成/保存/再読込を行う（wallとbuilding各2、その他各1、合計11fixture）。
カタログ全件のassertは新規9スキルの追加に合わせて更新し、旧6件も必須のまま維持した。

| Scene | 実測・確認 |
| --- | --- |
| A | 8×6×3m、外壁0.2、内寸7.6×5.6、1部屋、入口1、窓2、床/天井/屋根。実画像3枚を閲覧してarchitectural受理 |
| B | 12×8×3m、3室＋南廊下、室ドア3＋入口1、窓3。実画像3枚で間取り/可視性を確認して受理 |
| C | room02の窓を1.8×1.4mへ拡大。壁north/opening.window.room02/window.room02だけを変更。実画像3枚を閲覧して受理 |
| D | 過大窓、外側ドア、開口重複、負の壁/床厚、不正parent/WallRef、建具寸法不一致、未接続室、重複IDなどをpure compileで拒否 |

実メッシュの穴をcubeで塞ぐ、全法線を反転、壁厚を倍にする、廊下ドアを塞ぐ
4つの改変も、実Blenderのvalidatorで拒否した。
E2E自動テストは未閲覧を受理しない。目視評価をpytestで偽装せず、上記A/B/Cの
画像閲覧はこのCodexセッションで行い、path/hash/所見を永続化した。

実行証跡: artifacts/phase3a-scene-{a,b}、phase3a-scene-{a,b,c}.json、
phase3a-review-{a,b,c}.json、phase3a-accepted-{a,b,c}.json、phase3a-tests-final.*。
生成成果物はGit対象外。入力Spec/proposalだけをexamples/architectureへ保存する。

## 性能と残課題

初回の実機統合試験では、生成＋再読込は1室3.90秒、2室4.70秒、3室5.01秒
（並行検証中の値、preview・全CLI時間は含まない）。
Mesh/頂点/面はそれぞれ1室13/224/206、2室19/332/302、3室24/440/404。
各Skillの最新fixture単位の時間/件数はvalidation_evidence.tests[].metricsに記録。
必須参照のあるスキルは、そのfixtureの壁等を含む値であり、当該leaf単体の計測ではない。
大量Booleanも高密度メッシュも使わない。RAM/VRAMの強制上限は未実装。

PBR、外部アセット、家具、破壊/瓦礫、火災、地形、曲面建築、任意間取りの最適化、
本格増分生成、USD/Isaac Sim統合は未実装。窓/扉には固定slotと矩形という制限がある。
Ubuntu/CUDA/OptiXとVS Code GUI操作は未検証。確認範囲はCodexの解釈・CLI実行・
実Blender・画像閲覧・永続データによる編集である。
この小規模な直交建築基盤を維持してPhase 3Bの材質・見た目の改善へ進める。

最終の独立CLIベンチマーク（3室、build＋保存/再読込、previewなし）では
`/usr/bin/time -l`が実時間8.69秒、maximum resident set size=229,277,696 bytes
（約218.7MiB）を報告した。並行テスト中の1実測であり、プロセス群の合計使用RAMや
最大対応規模の保証ではない。証跡はartifacts/phase3a-benchmark-time.log。

最終の全回帰結果は **245 passed / 0 skipped / 0 failed、239.58秒**。
内訳は単体等214件と実Blender31件（既存23＋新規8）。
品質stageのfailed/not_runの区別と登録fixtureの対象スキル必須ガードを最終確認し、
関連する単体40件も再実行して40 passed（7.94秒）、品質関連を合わせた52件も成功。
wheel/sdistビルド、建築モジュール/manifest同梱、lock整合性、生成物/cache非同梱も確認した。

最終登録版でAとCの同一Revisionを新Attemptとして再ビルドし、各3画像を再閲覧・受理。
最終Cはbuilds/20261115T225802-3d8783865a7f/scene.blend、
室内画像はoperations/20261115T225820-5b6881f62fb3/preview.png
（いずれもartifacts/phase3a-scene-bからの相対パス）。
元B→Cの差分は3ノード、全node seed保持、最終accepted bundle整合性を確認した。
最終再ビルドはRevisionを増やさず、Attemptのみ追加している。

主な変更ファイル:

- architecture_layout.py（明示Spec作成/窓編集）、architecture_contracts.py（純粋契約）。
- blender/skills/architecture.py、新規9件のskills/arch_*.skill.json、entrypoints.json。
- compiler.py、contract_utils.py、registry.py、skill_testing.py（参照/契約/登録/計測）。
- intent.py、quality_profiles.py、workflow.py（建築profileと証跡・3視点）。
- blender/rendering.py、worker.py、validation.py（非破壊表示と汎用domain結果収集）。
- tests/test_architecture.py、test_architecture_integration.py、カタログ件数assert。
- examples/architectureのA/B SceneSpecとCodex解釈proposal。
- AGENTS.md、README.md、architecture.md、codex-workflow.md、本記録。
- pyproject.toml、__init__.py、uv.lock（0.4.0）。
