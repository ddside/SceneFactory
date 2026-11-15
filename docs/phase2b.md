# Phase 2B — 自然言語・参考画像からの生成と変更管理

実装日: 2026-11-15。アプリ0.3.0、uv Python 3.12.13、Blender 4.5.15 LTS
（内蔵Python 3.11.15）、macOS Apple M5で検証。

## 境界と正本

自然言語・画像の解釈はCodexが行い、アプリは構造化proposalを検証・実行する。
固定キーワードパーサー、独自UI、LLM API、DB、追加の実行時依存は導入しない。
既存6スキル、compile、protocol 2、実Blender Runner、ArtifactManifestを再利用。
部分再生成は行わず、編集も全シーンを新しいbuildへ生成する。

データフローは次の通り。

自然言語/画像 → Codex → SceneIntent + immutable SceneSpec Revision →
compile（派生BuildPlan/ResolvedScene/skills lock）→ Build Attempt →
構造検証/2視点preview → Quality Run → 実画像VisualReview → Presentation/Acceptance。

既存state.jsonだけを権威あるindex/working/accepted公開点として拡張した。
managedプロジェクトの仕様正本はworking Revisionの不変scene.jsonである。
ルートscene.jsonはlegacy bootstrapとして保持し、managed buildはそこを読まない。
Planは仕様から作る派生成果物であり、直接編集しない。
旧v1/v2 buildとpreviewは書き換えず、QualityReport v1はnot_evaluatedのまま保持する。

## SceneIntent schema 1

`intent.py`が厳格な検証、参照整合性、制約優先順位を実装する。

| 項目 | 内容 |
| --- | --- |
| intent_id / schema_version / created_at | 不変レコードの識別・版・日時 |
| raw_request | ユーザー原文 |
| reference_files | reference_id、プロジェクト相対path、sha256、format、metadata、inspection |
| observations | text、根拠reference_ids（viewed参照のみ） |
| assumptions | text、reference_ids、任意のconfidence |
| constraints | 下記の型付き制約 |
| unresolved_questions / unsupported_requests | textとblocking |
| requested_quality_profile | structural / preview_reviewed / basic_scene |
| generation_budget | 試行・時間・資源・改善停止条件 |

入力proposalにはraw_request、scene_spec、change_summaryが必須。
ID、日時、参照hashと画像metadataはアプリが作る。
参考画像の入力reference_filesはreference_id、source_path、inspectionを持つ。
画像はプロジェクト内referencesへコピーし、JSONへ埋め込まない。
PNGはストリーム検証、JPEGはヘッダ寸法検査まで（完全デコード検査ではない）。
閲覧の有無はCodexの明示的な評価記録であり、ファイル登録やmetadata検査から
推論しない。欠落・改変は再開・評価・公開時に検出する。

制約はconstraint_id、target_node_idまたはtarget_role（skill:ID）、type、
expected_value、strength（hard/soft）、source（kind/user/reference/assumptionとdetail、
任意reference_id）、confidence、toleranceを持つ。parameter_equalsにはpropertyも必要。
型はparameter_equals、location_equals（world位置）、node_count（著作ノード数）、
exists、grounded（実測world minZ）。一般的な幾何制約ソルバーではない。
ユーザー制約は同じ述語・対象・propertyの推定制約に優先し、採用しなかった推定も記録。
互いに満たせないhard制約、blocking未確定事項、未閲覧画像は実行を止める。
soft不一致は記録し、passedに改ざんしない。編集はconstraint_id単位で更新/継承する。

## Revision / Attempt / Quality / Publication

`workflow_store.py`はintents、revisions、attempts、quality-runs、visual-reviews、
presentations、acceptances、workflows、eventsをstate.jsonから参照する。
Intent、Revision snapshot、QualityRun、VisualReview、Presentation、Acceptance、
Workflow定義、Eventは不変かつhash管理。Attemptは進捗と成果物参照を更新する。
Revisionのparent/intent/hash/変更理由/changed_node_idsを不変保存し、status、
related_build_attempts、quality_run_idsは永続バック参照から投影する。
同じRevisionに複数Attempt、同じAttemptに複数QualityRunを持てる。

`publication.py`は品質適格性、working/Workflowとの一致、buildとsnapshotの一致を
検証し、Spec/Intent/参照/品質/画像/build一式のhashをAcceptance bundleへ保存する。
ファイルの準備完了後、最後の単一atomic state更新でacceptedを公開する。
途中のIO失敗では旧acceptedを維持し、未参照レコードは診断用に残る。
state公開の原子性は同一ファイルシステム上のreplaceであり、あらゆる電源断に対する
ディレクトリfsyncまでの永続性やネットワークFSの保証を主張しない。

Rollbackは既受理bundleのhashと関係性を検査して参照を切り替える。Blender起動も
現在のスキルによる再生成も不要。履歴・過去成果物を上書きしない。
rebuildは明示的な新Workflowと新Attemptであり、Rollbackとは別操作。

## Quality Profileと修復

| profile 1.0.0 | 必須stage |
| --- | --- |
| structural | specification、execution、structure |
| preview_reviewed | 上記 + visual |
| basic_scene | 上記 + domain（宣言された基本寸法/個数/配置制約のみ） |

全profileでhard要求適合を検査する。通常の対話生成はbasic_sceneを使う。
structuralを明示選択した受理は構造範囲だけで、視覚品質を保証しない。
QualityReport schema 2はprofile snapshot/digest、各stage、制約実測、findings、
visual_review_id、eligibilityを持つ。eligibleだけでは公開されず、bundle検査後に受理。
exportとtarget_compatibilityはnot_run。物理・写実性・画像一致度は未検証。

VisualReviewはattempt_id、reviewer、method=image_viewer、viewed=true、全previewの
path/sha256、notes、6検査のstate/reasonを持つ。6検査は要求物の可視性、配置、
主要構造の可視性、明らかな貫通/浮遊、参考画像との整合、要求適合性。
参照なしの場合のみreference_consistentをnot_applicableにできる。
実画像の閲覧をシステムだけで証明はできないため、Codexの誠実な記録が必要。
画像未閲覧・古いAttempt・hash不一致・必須検査未実行では視覚受理しない。

既定予算はmax_attempts=3、max_seconds=300、max_nodes=200、max_resolution=512、
max_samples=16、no_improvement_limit=1。解決後ノード数を制限し、render設定を上限で
制限する。時間予算はBlender各呼出しとレビューまで含む。RAM/VRAMのハード制限や
任意skillの頂点数上限ではない。実閲覧例では900秒を明示指定した。
再開も開始時刻・使用回数を保持する。

安全な決定的修復は既存parameter、root位置、root接地に限定する。
それ以外はneeds_repairとし、CodexがQualityReportを読んで同じIntent/profile/予算の
新Revisionをrepairで提案する。試行上限、時間超過、資源超過、改善なしで停止。
hard制約・品質基準・seedを修復で緩めない。子のworld位置修復を暗黙変換しない。

## CLIと再開

[Codex操作手順](codex-workflow.md)に会話履歴なしで実行できる手順を定義した。

```sh
uv run --locked scene-factory generate artifacts/example --proposal examples/workflows/natural-request.json
uv run --locked scene-factory edit artifacts/example --proposal edit.json
uv run --locked scene-factory review artifacts/example --file review.json
uv run --locked scene-factory repair artifacts/example --proposal repair.json
uv run --locked scene-factory history artifacts/example
uv run --locked scene-factory diff artifacts/example --from REV_A --to REV_B
uv run --locked scene-factory rollback artifacts/example --revision REV_A --reason '元に戻して'
uv run --locked scene-factory rebuild artifacts/example --revision REV_A
uv run --locked scene-factory resume artifacts/example
uv run --locked scene-factory resume artifacts/example --execute
uv run --locked scene-factory present artifacts/example
```

resumeはworking Spec/Intent、時系列の最新Intent、acceptedとその整合性、スキル、
Attempt/Quality履歴、preview、未解決事項、直近操作の失敗を返す。
read-onlyではBlender不要。中断したrunning Attemptはinterruptedとして新Attemptを
実行する。公開だけの失敗では再生成せず公開を再試行。dead PIDを証明できる古い
lockのみ回復し、生存PID・権限不明・不正lockは勝手に削除しない。
Presentationは要求要約、環境/スキル、status/profile、PNG/blend、accepted ID、
未対応/未実施検査、再編集方法を含む。

## 実測結果

全回帰は既存150件を含め197 passed（新規47件）。実Blenderは既存18件と新規5件。
新規単体42件では参照改変、原子的公開IO失敗、旧accepted保護、複数Attempt/Quality、
制約優先、予算/改善停止、古いレビュー拒否、lock、中断復旧、CLIを検査した。
単体の合成Blender/画像評価fixtureは実画像評価の代用にしない。
実Blender5件は生成・3編集・diff/rollback/rebuild、決定的修復/上限、render失敗、
未閲覧の非受理、別プロセス再開と中断再実行を確認した。

全試験コマンド（Macでの実際の実行先）:

```sh
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -q --junitxml=artifacts/phase2b-tests.xml
```

ログはartifacts/phase2b-tests.log。artifactsはGit管理対象外。
実Blender起動はサンドボックス制限外の承認済み実行。アプリ側の権限変更や偽の代替なし。

手動Codex E2Eでは自然言語の10×8×4m建物+周囲8柱+地面を解釈し、スキルを選択。
斜視と上面の実PNGを閲覧してbasic_sceneで受理した。
高さ5m→柱6本→右へ3mの3編集も各2画像を実閲覧して受理。
柱は建物の子として関連付け、移動ではbuilding.mainのみ変更し、子のID/seed/local配置を保持。
6柱への変更は残存6本を周囲に再配分し、変更理由を記録。
元のacceptedへのRollback後も全bundle hashが一致し、別CLIプロセスから状態を取得できた。
証跡: artifacts/phase2b-natural*、各review/accepted JSON。

参考画像例はプロジェクト所有のPhase 2A PNGを実閲覧し、観察/推定を区別して
既存recipe/cylinder/groundで簡易再現。生成した2画像も実閲覧しpreview_reviewedで受理。
正確な寸法・隠れた形状・テクスチャ再現は主張しない。
証跡: artifacts/phase2b-reference*。再生入力と出典はexamples/referencesに保存。

## 残課題と次段階

Ubuntu 24.04実機、CUDA/OptiX、VS Code GUI経由の操作は未検証。
本セッションのCodexによる解釈・CLI実行・画像閲覧・ファイルによる別プロセス再開までを
確認した。別チャットの記憶なしでも使える永続データと操作文書を用意したが、
実際のVS Code新規チャットGUIの操作確認を代替したとは扱わない。

Phase 2Cへはこの範囲のワークフロー基盤を維持して進められる。
高品質形状・PBR・ライセンス付き外部アセット、崩壊/洞窟、画像→3D復元、
本格増分ビルド、大規模最適化、USD/Isaac Sim本体、物理妥当性は未実装。
受理profileの範囲を超えて完成品質と呼ばないこと。

手動修復では親付きpillar.01を2m浮かせ、QualityReportで実測minZ=2、対象node_idと
接地制約違反を確認した。子のworld変換を勝手に推測する決定的修復は行われず、
Codexが親の変換を確認してlocal Z=0のrepair proposalを作成。
同じIntent/profile/予算の新Revision・第2Attemptで再検証し、2画像を実閲覧して
basic_sceneで受理した。証跡: artifacts/phase2b-repair*。
別の実機テストではroot接地の決定的修復とmax_attempts=1の停止も確認済み。
