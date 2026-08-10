# Implementation plan

No product code is changed in this task. After the user approves the final planning summary and a later turn runs `task.py start`, implement in this order.

## 1. Enforce the settled matrix-only boundary

- Implement schema version 1 as `policies × seeds` with shared immutable settings.
- Reject per-run/per-arm override syntax rather than leaving undocumented extension points.

## 2. Add the strict config owner

- Add one Python module for Pydantic schema, YAML loading, normalization, relative-path resolution, and source/normalized SHA-256 hashes.
- Use `extra="forbid"` throughout.
- Reuse an existing YAML parser if present; otherwise add only the minimum parser dependency.
- Keep runtime `Path` objects separate from public canonical hash material.
- Add one checked-in public example that represents the current Suzuki default/autonomous seeds 300–304, budget 2 experiment.

## 3. Replace hardcoded experiment-plan input

- Change the experiment planner currently represented by `benchmark/compare.py:74-101` to consume the validated config.
- Expand policies × seeds deterministically in authored order.
- Preserve fresh-output refusal and preflight-before-provider behavior.
- Keep provider generation seed recorded as unavailable.
- Remove hardcoded experiment constants only after the sample YAML produces the same normalized plan.

## 4. Add the config-backed CLI entry point

- Add `boagent experiment --config <path> [--plan]` (or the smallest equivalent at the supported experiment boundary).
- `--plan` emits normalized hashes and expanded public plan without filesystem mutation/provider startup.
- Execute mode reuses existing campaign initialization/run functions; factor shared functions only as necessary to avoid subprocess duplication.
- Do not add semantic CLI overrides beside `--config`.
- Preserve existing direct `boagent init`/`run` flags and omitted-policy default behavior.

## 5. Materialize declared provenance

- Add source-config safe identity, source hash, normalized hash, experiment name/policy, and initial acquisition values to generated `manifest.json`.
- Add declared normalized config hash to each `campaign-run-config.json` effective revision while retaining the existing effective `config_hash`.
- Add declared provenance and initial acquisition origin to Frame state with backward-compatible defaults for older state.
- Apply YAML acquisition defaults before provider startup without creating a fake agent revision.

## 6. Enforce resume and precedence

- Config-backed execution passes provider/model/thinking/policy explicitly.
- Environment remains secret-only for config-backed runs.
- If config-backed resume is supported, compare recorded normalized hash and fail on mismatch before changing state.
- Keep existing direct campaign resume behavior when no config is supplied.

## 7. Extend leakage safety

- Reject forbidden/unknown secret and hidden-data keys through the strict schema.
- Ensure validation errors never dump the complete YAML or values.
- Feed only allowlisted experiment identity/hash fields into existing leakage preflight.
- Verify no normalized config/manifest spread reaches prompts or tool context.
- Keep secrets outside both config hashes and public audit JSON.

## 8. Observable verification to run during implementation

Planning-only instruction for this turn says not to run these now.

- Config plan from two different CWDs yields identical normalized hashes and expanded outputs.
- Sample YAML expands to policies `default, autonomous_agent`, seeds `300..304`, budget `2`, provider `ai-modeling`, model `gpt-5.6-sol`, thinking `xhigh`, and fresh unique outputs.
- Unknown/forbidden keys, unsupported schema/enums, duplicate lists, invalid budget/beta, missing dataset, and output collision fail before mutation.
- Existing direct CLI contract tests remain green, especially omitted/default policy and initialization behavior.
- Generated manifest/run-audit/Frame provenance fields agree on declared hash while runtime acquisition revision changes only effective state/audit.
- Temporary bounds remain non-persistent and narrowing-only.
- Leakage preflight fails before model runtime for forbidden model-visible config/path/hidden fields.
- Synthetic secret values from environment never appear in YAML-derived hashes, manifests, run audit, prompt/context, or errors.
- Config-backed resume mismatch fails closed.
- Smoke: plan the sample; initialize one small campaign through config; observe generated artifacts; do not require a live provider call unless the implementation acceptance run explicitly includes it.

## 9. Review gates

- Cross-layer trace: YAML -> loader -> plan -> existing init -> manifest/Frame -> Supervisor -> run audit -> report.
- Compatibility trace: direct `init`/`run` with no config.
- Leakage trace: YAML fields -> normalized model-visible allowlist -> preflight; confirm hidden labels and absolute paths have no route.
- State trace: declared acquisition default -> effective runtime revision without declared-hash mutation.
- Remove obsolete hardcoded constants and any duplicate parsing/precedence path after the sample config cutover.

## Risky files / rollback points

- `src/boagent/agent_cli.py`: preserve direct CLI signatures and environment secret precedence.
- `benchmark/compare.py`: current hardcoded plan and reporting boundary; avoid coupling hidden-label reporting back into config loading.
- `src/boagent/state.py`: additive backward-compatible state fields only.
- `supervisor/supervisor.mjs`: do not broaden model-visible manifest/config surfaces.
- `supervisor/campaign.mjs`: keep leakage fail-closed and temporary-bound semantics.

Rollback by restoring the hardcoded planner and removing the config entry point/additive provenance fields; direct campaign commands and existing generated artifacts must remain usable throughout.
