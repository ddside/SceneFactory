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
  `BLENDER_EXECUTABLE`. Ubuntu compatibility needs real-machine validation.
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
