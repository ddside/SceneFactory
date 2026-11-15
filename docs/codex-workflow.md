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
