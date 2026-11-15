# Scene Factory

Python 3.12 / uvとBlender 4.5 LTS CLIで、JSON仕様から最小の3D環境を生成します。
Blender内蔵Python 3.11はアプリ環境から分離しています。BlenderのGUIやMCPは不要です。

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

仕様は`example/scene.json`を編集します。上記の既定initは従来のv1です。
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
