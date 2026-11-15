# Scene Factory

Python 3.12 / uvとBlender 4.5 LTS CLIで、JSON仕様から最小の3D環境を生成します。
Blender内蔵Python 3.11はアプリ環境から分離しています。BlenderのGUIやMCPは不要です。

Codexチャットでは自然言語と任意の参考画像を入力します。Codexが既存スキルを選び、
仕様作成・生成・検証・実画像レビューを操作します。継続編集、Revision履歴、
Rollback、制限付き修復、ファイルからの再開に対応します。
[操作手順](docs/codex-workflow.md)と[Phase 2Bの範囲・検証](docs/phase2b.md)を参照してください。
高度な画像→3D復元や写実的形状生成は未実装です。

```sh
# Codexが解釈済みproposalを作成して実行する例
uv run --locked scene-factory generate artifacts/example --proposal examples/workflows/natural-request.json
uv run --locked scene-factory resume artifacts/example
uv run --locked scene-factory history artifacts/example
uv run --locked scene-factory present artifacts/example
```

通常の生成はbasic_sceneを選び、実際のPNG閲覧とreview記録まで行います。
preview生成成功だけでは視覚検査をpassedにしません。acceptedは選択したprofileの
範囲だけを意味し、写実性や物理妥当性の保証ではありません。

```sh
uv python install 3.12
uv sync --locked
uv run --locked scene-factory doctor
uv run --locked scene-factory init example
uv run --locked scene-factory build example
uv run --locked scene-factory preview example --device cpu
uv run --locked scene-factory validate example
uv run --locked scene-factory status example
```

Blenderの指定は`--blender-path`、`SCENE_FACTORY_BLENDER`、プロジェクトの
`scene-factory.toml`、PATH、OS標準候補の順です。Blenderを自動インストールしません。
macOSの制限付きサンドボックスでは起動に失敗する場合があります。
runnerは権限を変更せず、エラーとログを残します。

従来のinit/buildでは仕様は`example/scene.json`を編集します。
generate/edit管理のプロジェクトでは不変Revisionが正本で、resumeした仕様から
新proposalを作ります。snapshotや派生Planを直接編集しません。
上記の既定initは従来のv1です。
v2では論理ノード・空間的な親子関係・typed inputと依存DAGを記述できます。
4直方体スキルに加え、円柱と複数部材のRecipeを利用できます。
いずれも契約実証用の小さな生成器で、写実的建築物の生成器ではありません。

```sh
uv run --locked scene-factory init v2-example --schema-version 2
uv run --locked scene-factory compile v2-example  # Blenderを起動しない
uv run --locked scene-factory build v2-example
uv run --locked scene-factory preview v2-example --device cpu
uv run --locked scene-factory validate v2-example
uv run --locked scene-factory skills list --query building
uv run --locked scene-factory skills show cylinder
# 既存入力を上書きせず、別ファイルへ変換
uv run --locked scene-factory migrate example/scene.json migrated-scene.json
```

仕様例: [v1](examples/minimal/scene.json)、[v2](examples/v2/scene.json)、
[v1相当のv2](examples/v2-equivalent/scene.json)。
共通契約、スキル追加、有効化手順は[docs/phase2a.md](docs/phase2a.md)にあります。
candidateスキルは通常生成で拒否し、実Blender試験と証跡なしに有効化しません。
プレビューの正本は`status`が示すoperations内のPNGです。
`validated`は構造成功を意味し、視覚品質の合格や最終的なacceptedではありません。

```sh
# Blenderなしのテスト（統合テストはskip）
uv run --locked pytest -q
# 両OS共通のCPU統合テスト。実際のインストール先を設定する。
SCENE_FACTORY_TEST_BLENDER=/path/to/blender uv run --locked pytest -v
# Macで旧Phase 0も含めて全実機試験を実施する場合
SCENE_FACTORY_TEST_BLENDER=/path/to/blender BLENDER_EXECUTABLE=/path/to/blender uv run --locked pytest -v
```

macOSで実Blenderによる動作を確認済み。Ubuntu 24.04実機とCUDA/OptiX、
VS Code GUI経由の操作は未検証です。USD生成の本体パイプラインへの組込みと
Isaac Sim互換性検証は後続Phaseで扱います。
