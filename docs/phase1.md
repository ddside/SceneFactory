# Phase 1 — 最小生成パイプライン

実装・確認日: 2026-11-15 (America/New_York)。
実行時: macOS 26.6.2 / arm64 / Apple M5 / 16GB、uv 0.11.26、
アプリCPython 3.12.13、Blender 4.5.15 LTS (5afeabba6097)、内蔵Python 3.11.15。

## 構成と判断

| モジュール | 責務 |
|---|---|
| cli.py | argparseによる6コマンド、JSON出力、失敗時exit 1 |
| spec.py | 依存なしの厳密検証、初期値適用、ID順正規化。Python 3.11でも利用 |
| config.py / platforms.py | TOML設定、実行ファイルの優先順位、OS固有候補の隔離 |
| runner.py | 引数配列によるsubprocess、ログ、timeout、終了コード、結果契約 |
| project.py / storage.py | 独立ビルド、hash検証、排他制御、原子的な完成版参照更新 |
| blender/generators.py | 安定IDを持つ決定的な形状と単純材質 |
| blender/validation.py | 実メッシュ・変換・単位・材質・ID・構造fingerprint検証 |
| blender/rendering.py | カメラ・照明・Cyclesデバイス選択・低負荷レンダー |
| blender/worker.py | 内蔵Python 3.11からJSON要求を実行するエントリーポイント |

実行時ライブラリ依存は追加していない。uv_buildをビルドバックエンドとして
uvコマンド用entry pointをインストールし、Blender専用コードも同じwheelに同梱。
アプリ側はbpy/pxrをimportしない。Blender側にはアプリのsite-packages、
PYTHONPATH、PYTHONHOME、VIRTUAL_ENVを渡さない。JSONの仕様・要求・結果で通信する。
アプリPythonの絶対パスは埋め込まない。

## Scene Specification v1

ルート必須: `schema_version`（整数1）、`scene_id`、`seed`（整数0..4294967295）、
`units`（文字列`m`のみ）、`objects`（配列1..1000個）。Z-up、メートルを採用。
`scene_id`と`stable_id`は1..64文字のASCII英数字/`.`/`_`/`-`、先頭は英数字。
stable_idはシーン内で一意。Blenderカスタム属性`stable_id`として保持する。

各オブジェクトは`stable_id`、`generator`、`transform`、`parameters`が必須。
未知フィールド、未登録generator、型違い、boolの数値流用、NaN/Infinity、
不正な寸法・座標、重複ID、重複JSONキー、不正JSONを拒否する。
例外にはフィールド名と理由を含める。入力を書換えず正規化したコピーを使う。

`transform`の省略可能な値:

| 値 | 初期値 | 範囲・意味 |
|---|---|---|
| location | [0,0,0] | 各成分-10000..10000メートル、底面中心の位置 |
| rotation_degrees | [0,0,0] | 各成分-360..360度、XYZ Euler |
| scale | [1,1,1] | 各成分0.001..100、正のスケールのみ |

全て3要素の数値配列。各生成器のローカルX=width、Y=depth、Z=height/thickness。
原点は底面中心（ローカルZ=0）、上面はZ=height/thickness。

| generator | parametersの初期値（メートル） | 出力 |
|---|---|---|
| ground | width=20, depth=20, thickness=0.2 | 厚みのある地面スラブ |
| box_building | width=6, depth=4, height=3 | 中実の建築ボリューム |
| pillar | width=0.4, depth=0.4, height=3 | 矩形断面の角柱 |
| roof | width=7, depth=5, thickness=0.25 | 平屋根スラブ |

parametersの各値は0.01..1000。省略した値は初期値で補う。
いずれも8頂点・6四角面の閉じた直方体。空洞、開口、勾配、破壊表現はない。
初期例のgroundはlocation.z=-0.2とし、上面をZ=0に置く。
buildingとroofの高さ合わせは仕様側で行い、依存関係はまだ自動計算しない。

オブジェクトをstable_id順に生成し、乱数はseedとIDから独立に導出する。
現在の形状はパラメータのみで決まり、seedは微小な材質色差に使う。
同一入力から同一の構造fingerprintが生成されることをMac実機で確認した。
fingerprintはID、generator、頂点、面、変換行列を6桁に丸めた構造のSHA-256。
`.blend`のバイト一致や画像の完全一致、異なるOS間でのhash一致は保証していない。

## CLIと設定

```sh
uv sync --locked
uv run --locked scene-factory doctor
uv run --locked scene-factory init example
uv run --locked scene-factory build example
uv run --locked scene-factory preview example --device cpu --resolution 256 --samples 8
uv run --locked scene-factory validate example
uv run --locked scene-factory status example
```

initは既存ディレクトリを上書きしない。`scene.json`、`scene-factory.toml`、
`state.json`を生成する。サンプルJSONはexamples/minimal/scene.json。
サンプルディレクトリ自体は初期化済みプロジェクトではない。
作成済みのexample/scene.jsonを編集するか、必要ならサンプルの内容をコピーする。

実行ファイルの優先順位:

1. CLI `--blender-path`
2. `SCENE_FACTORY_BLENDER`
3. PROJECT/scene-factory.tomlの`blender_path`
4. PATHの`blender`
5. platforms.pyのOS標準候補（Macのアプリバンドルを含む）

明示したパスが不正なら下位候補へ黙って切り替えず失敗する。
設定ファイル内の相対パスはプロジェクト基準、CLI/環境変数は現在ディレクトリ基準。
共通オプションはサブコマンドの前後で指定できる。

設定初期値はtimeout=120秒（許可範囲0より大きく3600以下）、device="cpu"、
resolution=256（32..1024）、samples=8（1..64）。未知設定はエラー。
CLI指定がTOML値を上書きする。Blenderをuvでインストール・更新しない。

doctorはOS・アーキテクチャ・アプリPython・Blenderのパス/バージョン/内蔵Pythonを
別々に報告する。デバイス列挙に加え、Cycles CPUと列挙されたGPU、EEVEEで
32×32の実レンダーを試す。列挙結果とrender_probesを分け、GPU検出だけで
レンダー可能と断定しない。各probeの失敗とバックエンド診断も残す。
起動不能時はexit 1で診断ディレクトリとstartup_errorを返す。

## ビルドと保護

PROJECT/builds/<UTC時刻-ランダムID>/に毎回新規保存する。

```text
build.json            staging / validated / failed、エラー、環境と実装hash
scene.json            初期値適用済みの入力スナップショット
scene.blend           生成シーン
result.json           生成ワーカーの実測結果
blender.log           stdout/stderrの統合ログ
request.json          ワーカー要求
execution.json        実コマンド、終了コード、timeout、経過秒、エラー
validation.json       別プロセスで再読込みした実測結果
reopen/               再読込み検証の要求・ログ・結果・実行記録
preview.png           プレビュー成功後の便利なコピー
preview.json          原本の操作ディレクトリとhashへの参照
```

アプリ側の入力検証で失敗した場合、Blender成果物は存在せずbuild.jsonに失敗理由を
保存する。全ファイルが常に存在するという意味ではない。
プロセス正常終了、結果JSONのok、成果物の存在、保存後の再読込み検証を別々に確認する。
検証はID集合、generator、頂点・面、ローカル寸法、位置、正のスケール、
world行列と境界、有限座標、単位、材質存在を対象とする。
予期しない親・modifier・constraint・animationも拒否する。
数値許容誤差は相対1e-6、絶対2e-5。幾何学/物理の完全性を証明するものではない。

build.jsonに入力・blend・生成結果・再検証結果のSHA-256、構造fingerprint、
アプリ/Blenderバージョン、Blender build hash、実装Pythonソース群のhashを保存する。
seedと生成設定はscene.json、実コマンドと時間はexecution.jsonで追跡する。
全検証を通った後だけstate.jsonのlast_successful_buildをos.replaceで更新する。
失敗ビルドと前回成功したビルドは独立して保持し、自動削除しない。

preview/validateの実行はPROJECT/operations/<id>/に隔離する。
既存成果物のhashと現行仕様の一致を確認してから、別プロセスで.blendを再読込みする。
仕様が変更されていればbuildを要求する。validateはプレビューなしでも実行可能。
previewは新しいPNGを検査してから公開し、失敗時に既存PNGを書き換えない。
statusは最新操作とエラー、最後に成功したbuild、主要成果物のhash整合性、
仕様の変更有無、プレビューの原本を表示する。

プロジェクトの変更操作は排他ロックを取り、同時書込みを拒否する。
強制終了後はstaging/ロックが残り得る。稼働中プロセスがないことを確認した後に
限り手動でロックを除去する。自動復旧、任意コードへの耐性、キャッシュ、
差分ビルドは未実装。外部ファイルを改変した場合は整合性検証で検出する。

## レンダリング

previewはCycles、初期CPU・256角・8サンプル、denoise無効。
生成メッシュ全体の境界から正投影カメラを配置し、SunとWorldで照明する。
カメラ/照明はpreview用プロセス内だけに追加し、validated blendは変更しない。

deviceは`cpu`、`metal`、`cuda`、`optix`、`auto`。
autoはBlenderが列挙したMetal→OptiX→CUDA→CPUの順に選び、結果に選択を記録する。
GPU選択時はCPUデバイスを無効にする。明示指定が利用不可ならエラー。
autoでも選択後のレンダー失敗時にCPUへ再試行しない。
EEVEEはdoctorの起動/レンダーprobe対象で、現行preview CLIはCyclesのみ。

## 検証記録

テストは単体の異常注入と実Blenderの統合テストを区別した。
subprocess単体テストでのモックを、Blender動作の根拠としては使っていない。

```sh
# 単体・移植性検証（Blender未指定なら統合テストはskip）
uv run --locked pytest -q
# Macで今回実施した全テスト
SCENE_FACTORY_TEST_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender \
uv run --locked pytest -v -s
uv lock --check
uv sync --locked
uv build --wheel
```

CLI実機確認にはartifacts/phase1-exampleを使い、init→build→CPU preview→validate→
statusを実行した。doctorも実行しCycles CPU/MetalとEEVEEの描画成功を確認。
auto previewはMetalを選んで成功。PNGを実際に開き、地面・建築ボリューム・角柱・
平屋根の描画を確認した。低サンプル画像であり写実性の検証ではない。
Phase 0の既存成果物は保持している。

実機テストは4生成器、ID、寸法/位置/回転/非一様scale、blend保存・再読込み、
CPU PNG、同一入力の構造hash一致、実Blender例外、実タイムアウト、
失敗時の成功build保護、利用不可デバイスでのPNG保護、改変メッシュの拒否を確認。
サンドボックス内doctorは実際にreturncode=-11となり、診断とログ保存を確認した。
制限外実行での成功はその制約を解消したという意味ではない。
runner自身は権限を変更しない。今回の制限外テストはツールの承認を受けて実行した。

最終テストは**62 passed、skipなし**（アプリ/単体/移植性54件、
実Blender8件=Phase 0の1件とPhase 1の7件）。
Phase 1の単独統合実行も7 passed。lock整合性・uv同期・wheelビルドと
worker/entry pointの同梱検査も成功した。
最終CLI受入はartifacts/phase1-acceptanceに別途保存し、全6コマンドの成功を確認。
証跡はartifacts/phase1-final-tests.log、phase1-integration-tests.log、phase1-doctor.json、
phase1-sandbox-doctor.json、phase1-example-status.json、phase1-auto-preview.json、
phase1-integration-*/配下。生成成果物はGitへ自動追加していない。
最終CLIの結果はphase1-init.json、phase1-build.json、phase1-preview.json、
phase1-validate.json、phase1-status.jsonに保存した。

## 移植性・残課題・Phase 2

アプリ用Python 3.12とJSON仕様は両OS共通。OS標準パスだけをplatforms.pyに隔離。
Ubuntu形式のCLIパス、PATH優先度、OS判定、LinuxにMac候補が混ざらないこと、
Blender共有コードの3.11構文、アプリimport時のbpy非依存をテストした。
Phase 1のCPU統合テストはOSによるskipを設けず、同じテストをUbuntuで実行可能。
Phase 0の旧Metal専用テストだけは非macOSでskipする。

Ubuntu 24.04 x86_64実機、CUDA/OptiX、VS Code GUI上のチャット経由の操作は
**未検証**。このCodexセッションからCLI一連の実行は成功したが、VS Codeの
GUI操作確認の代用とはしない。Ubuntu側ではuv同期後に同じCPUテストとdoctorを
実行し、GPU別probeを確認する必要がある。Ubuntu互換性確認済みとは断定しない。
新たなUSDエクスポートパイプライン、Isaac Sim、損傷/火災/洞窟、アセット/PBR、
継続編集や部分再生成は今回の実装対象外。

Mac CLI基盤はPhase 2の開発に使用できる。ただしPhase 1の全環境受入完了を
宣言するには、VS Codeの操作確認とUbuntu実機確認が残る。次フェーズは
生成器拡張に先立ち、Ubuntu CPUの受入と仕様/生成器のバージョン運用を整備する。
