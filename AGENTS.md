# Scene Factory Development Rules

## Mission and scope
Build reusable procedural 3D environments with Python, Blender CLI and bpy,
interactively controlled through Codex in VS Code. Blender MCP is unnecessary.
Target damaged buildings, post-fire facilities and caves in stages. Survivors,
VLM, robot control and exploration scenarios are outside scope.

## Architecture
- Read docs/architecture.md and inspect existing state before changing code.
- Keep application Python and Blender Python separate. Exchange versioned JSON
  files; do not install bpy in the application environment.
- Use uv-managed Python 3.12 on macOS and Ubuntu 24.04. Keep `.python-version`
  at `3.12` and `requires-python` at `>=3.12,<3.13`.
- Use `uv sync --locked` and `uv run --locked ...` as the standard workflow.
  Manage runtime dependencies with `uv add` and test dependencies with
  `uv add --dev`. Track `pyproject.toml`, `.python-version` and `uv.lock` in Git.
- Never embed OS-specific application Python paths in code. Do not use pip
  directly or recreate the obsolete Python 3.14 environment.
- Blender installation/execution is outside uv management. Keep Blender 4.5 LTS
  built-in Python 3.11 unchanged; select its executable via configuration or
  `SCENE_FACTORY_BLENDER` / `--blender-path`. `BLENDER_EXECUTABLE` is only used by
  the legacy Phase 0 test. Ubuntu compatibility needs real-machine validation.
- The validated, versioned Scene Specification is the source of truth.
- Reuse deterministic generators; extend the library when needed, rather than
  generating unrelated one-off scripts. Record seeds and configuration.
- Preserve stable object IDs and make builds idempotent where possible.
- Incremental rebuilds must invalidate all affected dependencies.
- Build in a new staging directory. Never overwrite the last validated scene
  before the replacement passes validation.
- Track asset licenses, provenance, hashes and build metadata. Do not introduce
  unverified external assets automatically.
- Separate visual geometry from optional collision geometry.
- Validate USD export and Isaac Sim compatibility as separate stages.

## Interactive changes
1. Inspect the project and classify the request as parameters, assets or code.
2. Reuse capabilities and implement the smallest appropriate change.
3. Validate the specification and run affected build steps.
4. Validate geometry, materials, transforms, references and output files.
5. Render previews when relevant and inspect accessible actual outputs.
6. Report changes, successes, failures and unverified requirements.
Ask questions only to avoid materially incorrect or destructive changes.

## Codex chat workflow (Phase 2B)
- Follow docs/codex-workflow.md and docs/phase2b.md. The user supplies natural
  language and optional images; Codex writes proposals and runs the commands.
  Do not introduce a keyword parser, chat UI, LLM API or Blender MCP.
- Start existing projects with `uv run --locked scene-factory resume PROJECT`.
  Inspect working Spec/Intent, accepted, skills/versions, attempts, quality,
  previews, remaining workflow budget and latest failure. Chat history is optional.
- Inspect `skills list/show`, reuse validated skills. Interpret the original
  request into SceneIntent plus SceneSpec v2. Record observations separately from
  assumptions; actually view supplied images before marking them viewed. Record
  inferred dimensions, uncertainty and unsupported features honestly.
- Use `generate PROJECT --proposal FILE` or `edit PROJECT --proposal FILE`.
  Normally choose basic_scene; use architectural for modular interiors and
  appearance for PBR architectural scenes.
  Preserve unrelated IDs/seeds. Managed projects use
  the working Revision snapshot; never edit snapshots, BuildPlan or the legacy
  root scene.json to change a managed scene.
- Read quality/presentation. Actually open every attempt preview before writing
  an image-bound VisualReview and invoking `review PROJECT --file FILE`.
  If images cannot be viewed, leave visual not_run and report the limitation.
- For needs_repair, read actual findings, identify the node/cause, propose the
  smallest parameter/placement correction via `repair PROJECT --proposal FILE`.
  Preserve Intent, hard constraints, profile, seeds and workflow budget. Stop on
  bounds/no improvement/unsupported work; never relax criteria to pass.
- Rollback switches to a previously accepted bundle without regeneration;
  rebuild creates a separate attempt using current skills. Inspect history/diff.
  `resume --execute` retains the original time/attempt budget and only recovers
  a lock when the saved PID is provably dead; do not remove a live process lock.
- Report Presentation status/profile, actual previews/blend, accepted ID,
  unsupported requests and unperformed checks. Do not call structural-scoped
  acceptance visual/physical quality. No intermediate user approval is required
  except execution permissions or materially blocking ambiguity.
- Phase 2B still rebuilds the full scene. High-quality generators,
  incremental caching and USD/Isaac Sim pipeline integration are later work.

## Phase 2A contracts and skill registration
- Read docs/phase2a.md before changing the compiler, registry, worker protocol or
  artifact/quality contracts. Preserve v1 originals and legacy validated builds.
- Use explicit `migrate SOURCE DESTINATION`; never migrate by overwriting input.
  New v2 projects use `init PROJECT --schema-version 2`; `compile PROJECT` must
  remain bpy-free and must not generate geometry.
- Logical node IDs and generated artifact IDs are different. Recipe child IDs
  derive from parent ID + local key; seeds derive from scene seed + node ID.
- Keep common validation shape-independent. Put topology/dimension/material checks
  in the skill validator and use independent measurements, not the generator's
  geometry construction function. The first declared artifact is the node frame.
- To add a skill: write a candidate manifest in src/scene_factory/skills, add its
  implementation and independent validator in blender/skills, and add reviewed
  bindings/support files in skills/entrypoints.json. Do not import bpy in the app.
- Validate schema, typed ports, exact dependency versions, recipe DAG and examples;
  add unit tests and real Blender integration tests. No central shape-specific
  validator branch should be needed for a new skill.
- Run passing unit tests with `--junitxml=PATH`, then run
  `uv run --locked scene-factory skills validate ID --activate --test-report PATH`.
  This tests each example with real Blender and reopening before activation.
  Candidate/disabled or stale-evidence skills must not run in normal builds.
  `--contract-only` is not sufficient for activation. Record changes in Git.
- When changing implementation/helpers/parameter contracts, return the skill to
  candidate or add a new exact version, rerun tests and refresh evidence. Pin all
  relevant helper source files in the reviewed binding; update dependencies too.
- Treat the local binding catalog as trusted reviewed code, not as a sandbox for
  arbitrary manifest Python. Never auto-enable external code or unverified assets.
- The canonical preview is the immutable operations PNG selected by preview.json.
  Publish only that single reference atomically. Do not overwrite legacy PNG copies.
- Structural `validated` is not `accepted`. QualityReport's visual/domain/export/
  target stages remain not_run unless their actual validation is implemented/run.
  Phase 2B adds profile-scoped QualityReport v2 and explicit acceptance; preserve
  old schema 1 not_evaluated reports. Incremental caching remains later work.

## Implementation and quality
- After code changes, run relevant checks and commit the completed changes.
  Include related documentation and lockfile updates. Do not include unrelated
  user changes or generated artifacts automatically; report failures honestly.
- Preserve existing files and follow current architecture; keep modules small.
- Add meaningful automated tests for new behavior. Use real Blender integration
  tests for bpy; never replace failing integration tests with mocks to pass.
- Do not introduce another orchestration framework or unnecessary services.
- Never silently substitute visually incorrect results.
- Process success does not prove visual quality; images do not prove geometric
  or physical correctness. Claim photorealism only after inspecting renders.
- Before completing a phase, run relevant tests and Blender integrations,
  inspect artifacts/logs, update documentation and identify remaining gaps.
- Do not claim full completion if required acceptance criteria remain unmet.
- Document version limits and unverified features. Do not install or upgrade
  Blender implicitly. A sandbox-related startup failure must be reported;
  changing sandbox settings is not an application-level fallback.

## Current integration probe
Use the exact command in docs/architecture.md. Outputs live under
artifacts/environment (original run) and artifacts/environment-python312-*
(uv test runs). Preserve previous artifacts; new runs use new directories.
`uv run --locked pytest` skips Blender without BLENDER_EXECUTABLE; a skipped
integration test is not proof of Blender compatibility. The current Metal
integration probe is macOS-specific and skips on other platforms.
Phase 1: set `SCENE_FACTORY_TEST_BLENDER` to run the common CPU integration tests
on macOS or Ubuntu. See docs/phase1.md for commands and acceptance evidence.
Phase 2A uses that same variable. New tests keep generated projects under
artifacts/test-runs/phase2a-*; registration checks use artifacts/skill-validation/.
Set both test variables to include all legacy Phase 0/1 tests. Ubuntu runtime and
CUDA/OptiX remain unverified until tested on the actual target hardware.

Phase 2B uses the same real-Blender test variables. Run the full regression suite
including the existing 150 cases and new workflow tests. Synthetic unit fixtures
are labeled test-only; they are never evidence of real Blender or image review.
Keep runtime outputs under ignored artifacts/; only intentional, documented
example input fixtures belong in Git.

## Phase 3A modular architecture
- Read docs/phase3a.md for geometry/coordinate/quality contracts. Reuse the nine
  arch_*@1.0.0 skills; preserve the six legacy skill meanings and version pins.
- Use architecture_layout.building_scene for a supported 1..3-room orthogonal
  layout or author explicit SceneSpec nodes. Height means clear height; document
  wall thickness, interior dimensions, corridor width and roof/slab assumptions.
- Keep wall/opening/fitting/room/corridor identities separate. Openings use stable
  wall slots (at most four per wall). A fitting edit must synchronize its opening
  and the wall slot; enlarge_window provides this focused three-node edit.
- WallRef/OpeningRef/SpaceRef are identity-bearing typed bindings with local
  dimension vectors; reference targets do not implicitly change transforms.
- Keep pure cross-node checks in the reviewed architectural contract binding and
  actual mesh checks in the skill validator. Include contract/support hashes in
  evidence. test_scenes supplies real registration fixtures for required ports.
- Choose architectural profile for architectural acceptance. Actual reopened
  domain evidence and actual review of overview/top/interior are required. A
  basic_scene pass is not architectural assurance. Do not claim physics/code
  compliance, photorealism or transparent glazing from these simplified models.
- Preview cover/south-wall hiding is temporary and must not alter saved geometry.
  Never delete roofs/walls from the authoritative Spec to expose an interior.
- Run existing 197 regressions plus new architecture tests with both Blender test
  variables. Explicitly retain Ubuntu/CUDA/OptiX as unverified in this phase.

## Phase 3B appearance and external assets
- Read docs/phase3b.md. Keep geometry, semantic Material records, texture bytes,
  Asset records, Providers and preview lighting separate. Build/compile must not
  query the network or silently substitute a different resource/version.
- Prefer cached exact refs via assets/materials list/show. Explicit acquisition
  uses a registered Provider; use the Poly Haven API with SceneFactory User-Agent
  and visible Poly Haven credit. Preserve asset CC0 separately from API terms.
- Local/Fake resources require explicit license metadata. Unknown license or lost
  source terms are not CC0. Never persist credentials in Catalog records.
- Keep catalogs immutable and content-addressed, stage complete dependencies,
  validate hash/size/checksum, and publish atomically. Preserve older versions.
  Each build freezes its resource snapshot/files; accepted includes their hashes.
- Use appearance profile for PBR architectural scenes. Verify actual shader
  values/links/color spaces, texture hashes, metric/tangent UV, material regions,
  import hierarchy/units/bounds and reopen results before actual image review.
- Normal maps mean OpenGL tangent space. Height is Bump, not geometric
  displacement. Glass/Principled and region shaders do not guarantee USD or
  Isaac Sim appearance. Preview uses only render-specific World+Sun settings.
- Avoid coincident floor/ground top faces. Place ground at the foundation bottom
  and use its actual elevation for external asset grounding; inspect the images.
- Do not change geometry nodes/seeds for a material-only edit. Use a new immutable
  MaterialRef and Revision, retain old accepted, and compare geometry fingerprints.
- External model execution currently supports a restricted static glTF subset.
  Preserve separate Mesh/Material/hierarchy; do not execute external scripts or
  import unsupported formats through a silent fallback. Use registered import
  Skill evidence and test_catalog fixtures, then real-provider E2E.
- Run the existing 245 tests plus new PBR/provider/resource/import tests with both
  Blender variables. Exclude opt-in live tests from ordinary regression and run
  them separately with SCENE_FACTORY_TEST_POLYHAVEN=1. A network skip is unverified.
- Track code/docs/own fixtures and example refs in Git; downloaded third-party
  bytes and generated artifacts remain under ignored artifacts/. Commit changes.
