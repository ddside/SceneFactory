# Codexによる生成・編集・再開手順

この文書はCodexの操作手順であり、Blenderの生成スキルとは別の概念である。
ユーザーは自然言語と任意の参考画像を提示するだけでよい。以下のJSON作成と
CLI操作はCodexが行う。専用チャットUI、APIキー、常駐LLMは不要。

1. `uv run --locked scene-factory skills list`、必要な`skills show ID`で
   validatedスキルを確認する。既存プロジェクトでは最初に`resume PROJECT`を読み、
   workingのSpec/Intent、accepted、失敗原因、予算、画像を確認する。
2. 原文をraw_requestへ保存する。参考画像は実際に閲覧して、見える事実を
   observations、不明な寸法・隠れた形状をassumptionsへ区別する。根拠のreference_id、
   confidence、inspectionの方法と所見を残す。閲覧できなければnot_viewedとし、
   見たことにしない。ユーザー明示条件を推定より優先する。
3. 再利用可能なスキルを選び、SceneSpec v2とIntentのproposalを作る。
   `examples/workflows/natural-request.json`が形式例である。参考画像のsource_pathは
   CLI実行ディレクトリから解決される。参照例は記録済みの解釈の再生用であり、
   別の画像へ流用してviewedを偽らない。合理的な既定値は記録して進める。
   未対応事項はunsupported_requestsに記録し、必須要求ならblocking=trueとする。
   重大な矛盾の場合のみ質問する。未登録スキルを実行しない。
4. 新規は`generate PROJECT --proposal FILE`、変更は`edit PROJECT --proposal FILE`。
   通常はbasic_sceneを使う。ユーザーから依頼されていない品質基準の緩和は禁止。
   コーディネータがcompile、実Blender build、再読込みvalidate、斜視/上面preview、
   qualityを実行する。変更時はresumeで得たSpecを基に、無関係なIDとseedを保つ。
   constraint_idが同じ制約は新指示で更新し、他の制約は継承する。
5. 出力のlatest_quality、latest_attempt、presentationを読む。awaiting_reviewなら
   attemptの全previewsを画像ツールで実際に閲覧する。6項目を評価し、正確なpathと
   SHA-256を持つVisualReview JSONを作って`review PROJECT --file FILE`へ渡す。
   画像を開けない場合はここで未評価と報告し、acceptedにしない。
6. needs_repairでは原因のnode_idと実測値を読み、既存スキルのパラメータ・配置だけを
   直した`{scene_spec, change_summary}`を`repair PROJECT --proposal FILE`へ渡す。
   同じWorkflowの試行数・時間・資源・改善停止条件を守る。制約やprofileは変更不可。
   stoppedをresumeして予算をリセットしない。自動修復不能を隠さない。
7. `present PROJECT`のstatus、profile、accepted Revision、PNG、blendパス、未対応・
   未実施検査をユーザーに報告する。画像成功を幾何・物理検証の代用にしない。
   構造のみのstructural受理を視覚品質の合格と呼ばない。

別チャットからも`resume PROJECT`で再開する。読み取りにはBlender不要。
`resume PROJECT --execute`は既存の予算で中断処理を再開する。生存中のプロセスの
lockは解除しない。再開では未完了Attemptをinterruptedとし、同じRevisionから
新Attemptを開始する。公開だけのIO失敗なら再ビルドせず公開を再試行する。

`history PROJECT`でRevisionと操作履歴、`diff PROJECT --from A --to B`で仕様差分を
確認する。「元に戻して」では対象を履歴から選び、
`rollback PROJECT --revision ID --reason '元の状態に戻して'`を実行する。
Rollbackは過去accepted bundleの整合性確認後の参照切替である。
現在のスキルによる再生成は`rebuild PROJECT [--revision ID]`で明示的に区別する。

VisualReviewの形式（ID/path/hashはresumeが返す当該Attemptの値を使う）:

```json
{
  "attempt_id": "attempt.ACTUAL_ID",
  "reviewer": "Codex",
  "method": "image_viewer",
  "viewed": true,
  "images": [{"path": "operations/ACTUAL_ID/preview.png", "sha256": "ACTUAL_HASH"}],
  "checks": {
    "requested_objects_visible": {"state": "passed", "reason": "実際に確認した所見"},
    "layout_reasonable": {"state": "passed", "reason": "実際に確認した所見"},
    "main_structure_visible": {"state": "passed", "reason": "実際に確認した所見"},
    "no_obvious_intersection_or_floating": {"state": "passed", "reason": "実際に確認した所見"},
    "reference_consistent": {"state": "not_applicable", "reason": "参考画像なし"},
    "request_conformance": {"state": "passed", "reason": "要求と実画像の比較所見"}
  },
  "notes": "閲覧した全視点、分かったこと、遮蔽や評価限界"
}
```

imagesには全preview（現在は2枚）を列挙する。上記は形式のみであり、
未閲覧のままコピーしてpassedを提出してはならない。不合格はfailedと所見を記録する。

## 内部構造を持つ建物（Phase 3A）

1. `skills list --query architecture`でarch_*スキルを確認する。
   通常のsolid building_recipeを室内モデルとして流用しない。
2. 「幅12m、奥行き8m、高さ3m、3室と廊下」ならCodexが
   `architecture_layout.building_scene(12,8,3,3)`で通常のSceneSpecを作れる。
   任意の平面図最適化ではなく、1〜3室の直交レイアウトである。
   高さは有効高さで、屋根上面は天井/屋根厚を足す。窓寸法/廊下幅/配置を
   assumptionsへ記録し、ユーザー明示条件を制約として保存する。
3. `examples/architecture/three-rooms-request.json`を形式例にproposalを作り、
   requested_quality_profile=architecturalでgenerateする。
4. domainの実Blender結果を読み、overview/top/interiorの全3画像を開く。
   topは天井/屋根、interiorはさらに南外壁をpreviewだけで非表示にしている。
   部屋の区別、廊下、ドア先の接続、窓、床、外観の天井/屋根を確認する。
   写実性やガラス透過を検証したとは呼ばない。
5. 「2番目の部屋の窓を大きく」ではresumeから部屋と窓を特定し、例えば
   `architecture_layout.enlarge_window(spec,'building.main.window.room02',1.8,1.4)`
   を使う。対象のwindow/opening/wall slotの3箇所だけを更新し、新Revisionへedit。
   stable IDとseedを保ち、再び実構造検査と全3画像の閲覧を行う。

壁は最大4矩形開口、レイアウトは矩形/直交、窓glassは簡易不透明部材。
未対応の曲面建築・任意間取り・破壊を代替形状で成功扱いしない。

## PBR・外部モデル（Phase 3B）

1. docs/phase3b.mdを読み、assets/materials list/showでcacheを優先する。
   新規取得はassets search/fetchでProviderを明示し、実在ID、variant、ライセンス、
   元asset/source URLを確認する。Poly Havenの出典表示とUser-Agentを維持する。
2. Concrete/Wood/Tile/Asphalt等はmaterials from-assetで正規化MaterialRecordを作る。
   get/refのhash・source licenseを確認し、appearance_layout.apply_building_materialsで
   通常のSceneSpecへbindingを記述する。TextureはsRGB/Non-Color、meters_per_repeat、
   木目回転を明示し、Heightを実幾何変位と呼ばない。
3. 外部モデルはasset_instance SkillのAssetRefで配置する。glTFは入力m/Y-upを検査し、
   source hierarchyを保持する。ground_zは実際の地面上面から指定する。建物床と地面の
   上面を同一にしない（床下面へ接触させる）。Source bboxから接地Zを計算できる。
4. requested_quality_profile=appearanceでgenerate/edit。buildはProviderを呼ばず、
   固定ref/byte/hashを解決する。cache欠落/破損は明示エラーとして報告し、fallbackしない。
5. 外観/上面/室内PNGを全て実閲覧する。材質、木目/タイル寸法、ガラス、rockの浮遊/
   貫通、黒い共面artifact、反射/白飛び/ノイズを確認する。必要なら追加視点と
   final-preview（高解像度/denoise）を独立operationとして生成し、実画像を確認する。
6. 「廊下だけ暗いタイル」では新しいMaterialRecord（例:元TileをTint派生）を作り、
   appearance.materials.tileのMaterialRefだけを更新する。ノード/seed/外壁binding/
   AssetRefを保ち、新Revisionで構造fingerprintと旧acceptedの保護を確認する。
7. 履歴/PresentationへSource/License/未実施検査も記録する。未閲覧はvisual not_run。
   Blenderの材質・照明をIsaac Simへそのまま移植可能と主張しない。

Live APIテストは通常回帰から分離し、失敗/未実施をFakeProviderで置き換えて成功扱いに
しない。Omniverse/Nucleus/Sketchfab/認証/USD import/exportはまだ対応していない。
