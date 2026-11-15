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

## Codex chat workflow
1. Inspect `scene.json`, `scene-factory.toml`, and `uv run --locked scene-factory status PROJECT`.
2. Translate natural language into a Scene Specification change using existing
   generators. For an unsupported generator, assess and implement/test it before
   running it; never execute an invented generator name.
3. Validate the specification with `scene_factory.spec.load_spec` through
   `uv run --locked python`, or let `build` perform validation before Blender starts.
4. Run `uv run --locked scene-factory build PROJECT` and inspect result/log files.
5. Run `preview PROJECT` when relevant, open its actual PNG, then `validate PROJECT`.
6. Report implementation, generated outputs, errors and unverified requirements.
   Use Codex chat itself; do not add a separate chat UI or Codex API integration.
7. Preserve previous successful builds. Phase 2A always rebuilds the full scene;
   incremental regeneration and complex continuing edits belong to later phases.

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
  SceneIntent, accepted Revision, automatic repair and caching are Phase 2B+ work.

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
