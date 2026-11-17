# Scene Factory

Python 3.12 / uvとBlender 4.5 LTS CLIで、JSON仕様から最小の3D環境を生成します。
Blender内蔵Python 3.11はアプリ環境から分離しています。BlenderのGUIやMCPは不要です。

Codexチャットでは自然言語と任意の参考画像を入力します。Codexが既存スキルを選び、
仕様作成・生成・検証・実画像レビューを操作します。継続編集、Revision履歴、
Rollback、制限付き修復、ファイルからの再開に対応します。
[操作手順](docs/codex-workflow.md)と[Phase 2Bの範囲・検証](docs/phase2b.md)を参照してください。
高度な画像→3D復元や写実的形状生成は未実装です。

正常環境から家具の転倒・脱落・破断、壁/床/天井/柱等の局所損傷を生成できます。
形状変更だけをcopy-on-writeで分離し、軽微な交差は許容、重大な貫通は受理しません。
[Phase 3D](docs/phase3d.md)と[損傷入力例の生成](examples/damage/create_proposals.py)を参照してください。
物理的な崩壊過程・安定性やIsaac Sim互換性を保証する機能ではありません。


災害固有の瓦礫・箱の散乱・煤・焼損・水位痕・泥・湿潤表面を独立したEffectとして
合成できます。指定seed、損傷元、領域、個数、寸法、分布を保持し、形状と表面効果を分離します。
[Phase 3E](docs/phase3e.md)と[入力例の生成](examples/effects/create_proposals.py)を参照してください。
受理にはdisaster_interiorと実画像レビューを使います。静的な災害後の状態であり、物理計算ではありません。


屋内生成はリビング・寝室・簡易キッチン、3部屋オフィス、店舗とバックヤードに対応。
机・椅子・棚・収納・モニターなどを独立部材の再利用Recipeで生成し、接地、支持、
交差、ドア前、通路幅を検証します。不足スキルはCodexが既存Registryへ実検証付きで
追加します。[Phase 3C](docs/phase3c.md)と[入力例](examples/interiors)を参照してください。
受理にはinterior profileと実際の画像確認を使用します。正常配置に加え、Phase 3Dで幾何的な損傷後の状態に対応します。物理は未実装です。


モジュラー建築は厚い壁・実際の開口・ドア/窓・床/天井・1〜3部屋と廊下に対応します。
例えば「幅12m、奥行き8m、高さ3m、3部屋と廊下、各室のドアと外壁の窓」と
Codexへ指示できます。建築ではarchitectural profileを使い、外観・上面・室内斜視を
実閲覧して受理します。詳細と制限は[Phase 3A](docs/phase3a.md)を参照してください。

PBRと外部アセットはProvider非依存Catalogで管理します。Poly Havenの実Concrete/Wood/
Tile/AsphaltとglTFモデルを取得・hash固定し、オフライン生成、透明Glass、材質だけの
編集に対応します。API利用時はPoly Havenを出典表示します。
[Phase 3Bの範囲・実測・制限](docs/phase3b.md)を参照してください。

```sh
uv run --locked scene-factory assets search --provider polyhaven --type textures --query concrete
uv run --locked scene-factory assets fetch --provider polyhaven --id concrete_wall_006 --variant 1k
uv run --locked scene-factory materials list
uv run --locked scene-factory final-preview artifacts/example
```

cacheは既定artifacts/asset-library、変更はSCENE_FACTORY_LIBRARYまたは--library。
生成時に外部素材を自動で別版へ差し替えません。ライブ試験は通常回帰と分離します。

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
4直方体スキルに加え、円柱と複数部材のRecipe、9つの建築スキルを利用できます。
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

```sh
# 通常回帰（live API試験を除く）
SCENE_FACTORY_TEST_BLENDER=/path/to/blender BLENDER_EXECUTABLE=/path/to/blender \
uv run --locked pytest -q --ignore=tests/test_polyhaven_live.py
# 明示的な実Poly Haven試験
SCENE_FACTORY_TEST_POLYHAVEN=1 SCENE_FACTORY_TEST_BLENDER=/path/to/blender \
uv run --locked pytest -q tests/test_polyhaven_live.py
```
