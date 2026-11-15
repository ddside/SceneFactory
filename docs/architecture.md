# Scene Factory — 初期アーキテクチャと実環境

調査日: 2026-11-15 (America/New_York)。空の作業ディレクトリから開始。
このフェーズは環境調査と最小統合検証のみ。本格的な生成器は未実装。

## uv / Python 3.12への設計変更（現行手順）

macOSとUbuntu 24.04のアプリ用環境はPython 3.12系列とuvで統一する。
Mac実測はuv 0.11.26、CPython 3.12.13、pytest 9.2.0。
`.python-version`は`3.12`、pyprojectのrequires-pythonは`>=3.12,<3.13`。
パッチ番号はこの指定では固定しないため、別マシンでは3.12内の別パッチが
選択され得る。uv.lockはパッケージの解決結果を固定するものである。

```sh
uv --version
uv python install 3.12
uv sync --locked
uv run --locked python --version
uv run --locked pytest -v
uv lock --check
```

初回のlock生成は`uv sync`で実施した。以後は上記のlocked手順を標準とし、
依存追加は`uv add <package>`、テスト用は`uv add --dev <package>`を使う。
`pyproject.toml`、`.python-version`、`uv.lock`を合わせてGit管理する。
本作業ではGit未初期化だったため初期化してファイルをステージした。
Phase 0の設定・コードはコミット済み。仮想環境とuvキャッシュはGit対象外。
当面は実行時依存なし、devはpytestとその推移的依存。
パッケージ本体は未実装のため`tool.uv.package=false`とし、配布用ビルド
バックエンドはまだ導入しない。

整理作業では`.DS_Store`、`.pytest_cache`、ローカル`.uv-cache`、
`tests/__pycache__`を削除した。いずれも再生成可能な一時ファイル。
現行`.venv`、検証ログ・USD・画像は保持する。

uvの[lock/sync公式仕様](https://docs.astral.sh/uv/concepts/projects/sync/)と
[依存管理](https://docs.astral.sh/uv/concepts/projects/dependencies/)に従う。
uvの既定キャッシュはこのセッションのサンドボックスで書込み不可だった。
`UV_CACHE_DIR=.uv-cache`での一覧確認は成功し、インストール・同期・実機テストは
承認された制限外実行で行った。通常の端末で同じ権限問題があるとは断定しない。

### 移行・影響確認

移行時は旧`.venv`（3.14.7）を`.venv-backups/python314-phase0`へ退避し、
新しい`.venv`をuvで作成した。Python 3.12と実Blenderの検証成功後、
ユーザーの指示により不要になった`.venv-backups`を削除した（約13MB）。
既存の成果物は保持し、システム/HomebrewのPythonは変更していない。

リポジトリのコードと設定を検索し、旧Pythonパスや3.14固有APIを使用する
処理は見つからなかった。3.14の記載・絶対パスは初回調査の履歴としてのみ
下記に残す。実行コードにOS固有のPythonパスは埋め込まない。
Blender用スクリプトは3.11互換の構文を維持する。
Python 3.12上で環境契約、TOML読込み、Blenderスクリプトの3.11構文解析、
実Blender subprocess呼出しとJSON読込みをテストし、移行による不具合は
今回のPhase 0範囲では検出されなかった。

Blenderのインストール、バイナリ起動、内蔵Pythonはuv管理対象外。
アプリPython 3.12から別プロセスを起動し、bpyは引き続き内蔵3.11.15で実行。
Blender実行ファイルは環境変数で渡す。Macでの実行例:

```sh
BLENDER_EXECUTABLE=/Applications/Blender.app/Contents/MacOS/Blender uv run --locked pytest -v -s
```

### 再検証結果

上記の実Blender付きテストは **2 passed、skipなし**。
`uv lock --check`、`uv sync --locked`も成功。
ログは `artifacts/python312-tests.log`、新しい成果物は
`artifacts/environment-python312-f7655v9f/` に保存した。
USD出力・pxr再読込み、Cycles CPU、EEVEE、Cycles Metalの4項目すべて成功。
Blender 4.5.15 / 内蔵Python 3.11.15であることもテストで確認。
PNG 3枚を開いて立方体の描画を再確認した。旧artifacts/environmentは未変更。
繰り返し実行時も成果物の出力先を毎回新規作成し、上書きを避ける。

### Ubuntu 24.04の扱いと未検証項目

Ubuntuでも上記のuv install/sync/run手順を設計上の標準とする。
**Ubuntu実機でのPython環境構築・pytest・Blender起動は未検証**。
共通設定とlockを用意したことは実機互換性の確認を意味しない。
Ubuntu上で`uv python install 3.12`、`uv sync --locked`、共通テストを実行し、
その後Blender 4.5 LTSの実行ファイル・ライブラリ・GPUバックエンドを確認する。
現状の実BlenderテストはmacOS Metal専用のため非macOSでskipする。
UbuntuのCPU/GPU実検証はLinux向けprobeを追加してから行い、skipを成功扱いしない。
MacでもBLENDER_EXECUTABLE未指定なら統合テストはskipする。
Isaac Sim互換性、Ubuntu GPUバックエンド、VS Code GUIからの往復操作は未検証。

## 実測環境

| 項目 | 確認結果 |
|---|---|
| OS | macOS 26.6.2 / build 25G83、Darwin 25.6.0、arm64 |
| CPU / RAM | MacBook Air Mac17,4、Apple M5、10 cores (4P+6E)、16 GB |
| GPU | Apple M5、10 cores、Metal Supported (system_profiler) |
| システムPython | /usr/bin/python3 → Xcode配下、3.9.6 |
| アプリ用Python（更新後） | uv管理 CPython 3.12.13、arm64、.venv |
| Blender | /Applications/Blender.app/Contents/MacOS/Blender、4.5.15 LTS、hash 5afeabba6097 |
| Blender Python | 3.11.15、CLI内でsys.version確認済み |
| Codex | codex-cli 0.169.0-alpha.11.1、VS Code拡張26.1111.21308のmacos-aarch64バイナリ |

CodexのPATH alias作成は権限警告あり。ただしバージョン取得可能。
VS Code拡張ディレクトリは確認済み。VS Code GUIからの往復操作は未検証。
BlenderはPATHにないため絶対パスを使う。ハードウェア調査に警告が出たが
CPU/GPU情報は取得できた。個体識別情報は本ドキュメントに保存しない。

## 起動条件と初回調査コマンド（移行前の履歴）

通常の制限付き実行はPython実行前にexit 139でクラッシュ。
crash backtraceはMetalデバイス検出の supports_barycentric_whitelist /
MTLBackend::metal_is_supported を指す。同一の最小コマンドを制限外で実行すると
exit 0となりbpyと内蔵Pythonのバージョン、build_options.usd=Trueを確認できた。
サンドボックス条件に依存することは実測済みだが、根本原因は未確定。

```sh
uname -a
sw_vers
system_profiler SPHardwareDataType SPDisplaysDataType
command -v python3 blender codex
python3 --version
codex --version
find /Applications /Users/mizuho/Applications /opt/homebrew /usr/local -iname '*blender*' -maxdepth 5 2>/dev/null
/Applications/Blender.app/Contents/MacOS/Blender --version
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python-expr 'import bpy,sys; print("SF_RUNTIME",bpy.app.version_string,sys.version); print("SF_USD",bpy.app.build_options.usd)'
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -c 'import sys; print(sys.version); print(sys.prefix != sys.base_prefix)'
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python-exit-code 1 --python scripts/blender_probe.py > artifacts/environment/blender.log 2>&1
```

Blender起動は今回承認された制限外実行で検証。通常のCodex実行条件では
同じ起動制約が残る。--python-exit-code 1でPython例外をプロセス失敗にする。
初回ファイル探索の一部はzshの未一致globで失敗したためfindで確認し直した。

## 技術選定

### 最小統合検証の結果

`scripts/blender_probe.py`を実Blenderで実行しexit 0。
詳細は `artifacts/environment/report.json` と `blender.log` に保存した。

| テスト | 結果・確認範囲 |
|---|---|
| bpy起動 / API | 成功。factory startupのcube 8頂点確認、属性設定、レンダー設定を実行 |
| USD export / pxr stage再読込 | 成功。Mesh 1個、/root/Cube/Cube、Z-up、metersPerUnit=1 |
| Cycles CPU | 成功。64×64、4 samples、PNG保存 |
| EEVEE | 成功。64×64 PNG保存 |
| Cycles Metal | 成功。Apple M5 (GPU - 10 cores)を列挙し、CPUデバイス無効・GPU有効でレンダー |
| アプリ仮想環境 | 成功。Python 3.14.7、sys.prefix != sys.base_prefix |
| スクリプト構文 / 結果JSON | 成功。アプリPythonでAST解析、4項目成功を確認 |
| 制限付きBlender起動 | 失敗。exit 139、制限外で成功。運用上の制約として残る |

3枚のPNGを実際に開き、グレー背景に立方体が描画されていることを確認。
これはCLI出力の目視確認であり、写実性や複雑シーン品質の検証ではない。
EEVEE画像名の `_cpu` はprobe関数のデフォルト引数由来で、EEVEEのCPU実行を
意味しない。EEVEEのデバイス詳細は測定していない。
reportのenginesは静的RNA enum取得結果でEEVEEのみだが、動的登録された
Cyclesは実レンダーで使用できた。エンジン全一覧としては扱わない。
USDAテキストでも `userProperties:sf_id = "probe.cube"` を目視確認した。
一般のID往復保持や再インポートの自動検証は今後の課題。
Metal初回カーネルロード込み約43秒、ログのデバイスメモリ表示は約2.8GB。
ベンチマーク用途の測定ではない。

アプリ側は両OSでuv管理のPython 3.12系列に統一する。実行時依存は現状なし、
テスト依存はdevグループのpytestをuv.lockで管理する。JSONを最初の
Scene Specificationとし、バージョン、単位、seed、stable IDを必須にする。
JSON Schema相当の検証契約を次フェーズに実装する。YAMLは要求が生じた時に
安全なパーサと依存互換性を検証して追加する。現時点で外部パッケージなし。

Blender側は4.5.15 LTS / Python 3.11に固定してbpyを使う。アプリ側の
site-packagesやPYTHONPATHは注入しない。共有データ型はJSON互換に制限し、
共有コードが必要な場合は3.11互換を守る。アプリ側でbpy/pxrをimportしない。
Blender APIは実機のRNAと統合テストを基準に検証し、別バージョンへの互換性は
保証しない。今回のprobeで使用するAPI以外は未検証。

アプリのsubprocess引数配列でBlender CLIを呼び、タイムアウト・終了コード・
JSON結果・ログ・成果物を確認する構成を採る。shell=Trueは使わない。
Blenderパスは設定可能にし、見つからない場合は明確に失敗させる。

プレビューはEEVEE、品質確認はCyclesを候補とする。Metalは明示選択し、
CPUへの切替はユーザーに記録して行う。小さいprobeは性能保証ではない。
16GB共有メモリを考慮し、インスタンス・解像度・ポリゴン数の上限を設ける。

## 目標データフロー（未実装）

自然言語要求 → Codexによる仕様/生成器の変更 → 仕様検証 → 依存DAG計画 →
Blenderワーカー → 構造検証 → プレビュー/画像検査 → USD出力/検証 →
validated manifestの更新 → 別環境でIsaac Sim検証。

想定ディレクトリは src/scene_factory（CLI・仕様・計画・実行）、
blender/（ワーカー・再利用生成器・検証）、specs/、assets/、tests/、
builds/<build-id>/。まだこれらの空の骨組みは作らない。

キャッシュキーは仕様、生成器バージョン/コード、Blenderバージョン、seed、
入力アセットhash、依存成果物hashから計算する。material変更とgeometry変更の
依存を区別し、下流のレンダー/USDは必要に応じ再実行する。
stable IDは表示名と分離し、カスタム属性とmanifestで追跡する。
USDへの属性保持は別途テストする。build-idごとのstagingに保存し、全必須検証
成功後にvalidated参照を原子的に更新する。失敗ビルドは診断用に隔離する。
異なるBlender起動間の部分再生成は、まずモジュール単位の.blend成果物と
manifestによる再利用を設計・検証する。完全な増分更新は未実装。

アセット台帳は出典、ライセンス、改変、hash、テクスチャ参照、使用箇所を持つ。
PBRは最初にPrincipled BSDFの限定サブセットとUV/テクスチャを扱い、USD変換時の
見た目・相対参照を検証する。複雑なノードの可搬性を仮定しない。

## USDとIsaac Sim

USDビルド対応とエクスポータ存在だけでは実用互換性を保証しない。
probeはデフォルトcubeをUSDAに出力し、内蔵pxrでstageを再度開きMesh数、
upAxis、metersPerUnitを確認する。テクスチャ、インスタンス、衝突、物性、
PhysXスキーマ、参照の再配置、Isaac Sim読込みは未検証。

Isaac Simの実行確認には対応する別環境が必要。公式のワークステーション手順は
Windows/LinuxとGPUを対象とする。このmacOS機での動作を前提にしない。
導入時に対象バージョンを固定し、当該要件とCompatibility Checkerを確認する。
[NVIDIA公式インストール手順](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_workstation.html)
および[要件](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)。

## 段階的実装と受入条件

1. 仕様v1・標準ライブラリCLI・Blender runner。ID/単位/seedの検証、異常仕様、
   タイムアウト、例外、成果物欠落をテストし、前回validated成果物の保護を確認。
2. 最小の部屋/構造生成器。決定性、再実行、stable ID、寸法、変換、法線、
   材質を実Blenderで検証。画像を実際に確認する。
3. DAGと部分再生成。独立モジュール再利用、依存無効化、失敗時復旧を検証。
4. ライセンス管理付きアセット、PBR、照明、プレビューと品質レポート。
   欠落テクスチャ、参照切れ、メモリ予算を検査。
5. 地震損傷建築物 → 火災後施設 → 地下洞窟の順に生成器を拡張。
   視覚的損傷を物理シミュレーションの妥当性と混同しない。
6. USDパッケージの再配置・構造検証後、対応機のIsaac Simで独立受入。
   単位、軸、材質、参照、任意のcollisionを確認。

次フェーズ前提: Blenderの制限外CLI実行が可能な運用、今回のバージョン固定、
仕様v1の範囲と最小シーンの確定。Isaac Sim用機材はUSD受入段階までに用意する。
