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

仕様は`example/scene.json`を編集します。初期仕様は4種類の直方体生成器
（地面、建物の塊、角柱、平屋根）です。写実的建築物や室内の生成器ではありません。
例は[examples/minimal/scene.json](examples/minimal/scene.json)、
仕様契約と運用は[docs/phase1.md](docs/phase1.md)にあります。

```sh
# Blenderなしのテスト（統合テストはskip）
uv run --locked pytest -q
# 両OS共通のCPU統合テスト。実際のインストール先を設定する。
SCENE_FACTORY_TEST_BLENDER=/path/to/blender uv run --locked pytest -v
```

macOSで実Blenderによる動作を確認済み。Ubuntu 24.04実機とCUDA/OptiX、
VS Code GUI経由の操作は未検証です。USD生成の本体パイプラインへの組込みと
Isaac Sim互換性検証は後続Phaseで扱います。
