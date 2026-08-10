# Experiment parameter configuration research

## Scope and recommendation

Standardize one public, human-authored YAML document as the reproducibility input for a complete experiment run plan (one or more campaign profiles crossed with fixed campaign seeds). Keep the existing `boagent init` and `boagent run` flags usable for ad-hoc/single-campaign work. Add config consumption at the experiment-plan/orchestration boundary rather than making generated campaign artifacts into inputs.

The YAML is the immutable declared intent. `manifest.json`, `campaign-run-config.json`, and `frame/state.json` remain generated records with distinct responsibilities; none becomes a second hand-edited configuration source.

## Repository evidence

### Existing CLI and campaign initialization

- `src/boagent/agent_cli.py:50-65` defines `boagent init` inputs: `dataset_root`, `output`, `seed=100`, `budget=40`, `target="Yield"`, and `direction="maximize"`.
- `src/boagent/agent_cli.py:66-89` resolves dataset/output paths, rejects an existing output directory, checks train/candidate schema alignment, generates `campaign_id`, and writes `manifest.json` including dataset path, seed, budget, target/direction, and prior audit metadata.
- `src/boagent/agent_cli.py:90-121` derives public options and label-free dataset summary, writes `TASK.md`/`CAMPAIGN.md`, creates `frame/`, and invokes `lenz create` with the campaign boundary values.
- `src/boagent/agent_cli.py:128-152` defines `boagent run` inputs: campaign, model, thinking, and policy; policy is restricted to `default|autonomous_agent`, omitted policy preserves `default`, receipt key is passed through environment, and the Node Supervisor is invoked with explicit run arguments.
- `src/boagent/agent_cli.py:23-31` loads repository `.env` without overriding an already exported environment and constructs the child environment. Secrets therefore belong to environment resolution, not a public config.

### Frame state and runtime steering

- `src/boagent/state.py:47-66` persists campaign boundary fields (`campaign_id`, public root, target, direction, seed, budget, features/categories), generated trials/events/revisions, and initial optimization defaults (`acqf="noisy_logei"`, `beta=2.0`, objectives, constraints, original domain, active bounds).
- `src/boagent/state.py:68-94` migrates older persisted state by defaulting objectives, constraints, original domain, and active bounds.
- `src/boagent/cli.py:105-165` creates Frame state from `train.csv` and `test_features.csv`; feature/category topology is derived from public data and historical rows, while target/direction/seed/budget/campaign ID enter through CLI arguments.
- `src/boagent/cli.py:363-406` allows audited runtime acquisition changes (`acqf`, `beta`) and increments `configuration_revision` with a rationale-bearing event.
- `src/boagent/cli.py:408-455` allows persistent runtime revisions of active bounds, objective, and constraints for profiles that expose those tools; bounds must remain inside `original_domain`, objective is currently single-objective, and non-empty constraints are unsupported.
- `src/boagent/cli.py:91-103` combines persistent active bounds with temporary command bounds by intersection; temporary bounds narrow rather than widen the active domain.
- `supervisor/campaign.mjs:159-167` exposes temporary `bounds`, `around`, and `radius` on `lenz_suggest` without persisting them.
- `supervisor/campaign.mjs:211-227` exposes permanent bounds/objectives/constraints only outside the autonomous profile. Autonomous runtime retains `lenz_set_acqf` but omits permanent domain mutation.

### Supervisor configuration and audit

- `supervisor/supervisor.mjs:13-31` currently parses `--campaign`, `--model`, `--thinking`, and `--policy`; provider is fixed to `ai-modeling`, model may fall back to `BOAGENT_MODEL`, thinking defaults to `xhigh`, policy defaults to `default`.
- `supervisor/supervisor.mjs:61-65` builds generated run audit data: campaign ID, provider/model/thinking/policy, system/reference/prompt hashes, prior hash/source/scan/provenance, provider-generation-seed limitation, code revision hash, and `config_hash`.
- `supervisor/supervisor.mjs:96-102` gives the model an allowlisted effective manifest rather than the full persisted manifest; campaign ID, seed, budget, target, and direction are visible, but dataset paths are excluded.
- `supervisor/supervisor.mjs:154-168` runs leakage preflight before model runtime/provider startup, adds its result to run config, hashes the final run config, and appends a revision to `campaign-run-config.json` only when effective values differ.
- `supervisor/campaign.mjs:329-339` rejects model-visible dataset/public paths, `test.csv`, global-best/hidden-rank terms, enabled runtime resource surfaces, or incomplete prior audit metadata.
- `supervisor/campaign.mjs:303-317` allowlists autonomous initial context fields and excludes ranked proposals/path fields.

### Current experiment runner

- `benchmark/compare.py:74-76` hardcodes experiment seeds `300..304` and profiles `default|autonomous_agent`.
- `benchmark/compare.py:78-101` hardcodes the reproducibility plan: policy × seed matrix, budget 2, provider `ai-modeling`, model `gpt-5.6-sol`, thinking `xhigh`, provider generation seed unavailable, output paths, init/run commands, and mandatory leakage preflight. It refuses an existing campaign directory.
- `tests/test_benchmark_compare.py:83-95` contracts those hardcoded values and fresh-output behavior.
- Archived planning records the same fixed experiment boundary at `.trellis/tasks/archive/2026-08/08-08-autonomous-agent-bo-experiment/prd.md:69-77` and `.trellis/tasks/archive/2026-08/08-08-autonomous-agent-bo-experiment/design.md:177-190`.

### Existing contract tests relevant to configuration

- `tests/test_cli_contract.py:21-37` exercises explicit Frame creation values.
- `tests/test_cli_contract.py:121-130` protects legacy state migration/default domain configuration.
- `tests/test_cli_contract.py:148-162` protects persistent versus temporary steering.
- `tests/test_cli_contract.py:170-183` protects numeric interval semantics and the rule that temporary bounds only narrow.
- `tests/test_cli_contract.py:329-378` protects label-free dataset summaries and prior audit metadata.
- `supervisor/campaign.test.mjs:160-179` protects autonomous tool restrictions.
- `supervisor/campaign.test.mjs:213-218` protects fail-closed leakage preflight.
- `.trellis/spec/backend/quality-guidelines.md:26-79` codifies omitted-policy compatibility, allowlisted prompts, leakage preflight, runtime mutability, and generated audit fields.

## Parameter classification

| Parameter / source | Classification | Planned ownership and semantics |
|---|---|---|
| Config schema version | Immutable input | Required top-level integer, initially `1`; reject unsupported versions. |
| Experiment name/slug | Immutable input | Public stable identity used for readable output/audit metadata; not a generated campaign UUID. |
| Dataset root | Immutable input, sensitive path in generated local manifest but forbidden model-visible | YAML path resolved relative to YAML file; must contain public inputs. Never place contents or absolute resolved path in model-visible context. |
| Output root | Immutable input | YAML path resolved relative to YAML file. Every campaign output must be new; no overwrite/resume-by-accident. |
| Profiles/policies | Immutable input | Non-empty unique list of supported public policy names; current values `default`, `autonomous_agent`. Crossed with seeds deterministically. |
| Campaign seeds | Immutable input | Non-empty unique integer list, preserved in author order. Controls campaign/model initialization where supported, not provider generation. |
| Budget | Immutable input | Positive integer applied to every generated campaign unless the future schema explicitly introduces per-run entries. Runtime cannot increase or decrease it. |
| Target and direction | Immutable input | Target string and `maximize|minimize`; determines receipts, Frame objective baseline, export/report semantics. Runtime objective mutation remains profile-specific steering, not a rewrite of declared experiment intent. Audit both declared and effective values. |
| Provider | Immutable input for reproducible plan | Public provider identifier, default may be written explicitly by generated example but should not be secret. Current runtime supports `ai-modeling`; validate against supported values. |
| Model | Immutable input for reproducible plan | Public model identifier. Existing ad-hoc `boagent run --model` remains usable. A config-backed run must audit any explicit override. |
| Thinking | Immutable input for reproducible plan | Public enum/string accepted by embedded runtime; existing default `xhigh`. |
| Provider generation seed | Audit-only output | Record `unavailable`; do not pretend campaign seed makes provider output replayable. |
| Initial acquisition function | Initial runtime default | YAML may declare `runtime_defaults.acquisition.name`; initialize Frame before the first agent turn. It is not immutable because allowed profiles/agents may revise it. Default remains `noisy_logei`. |
| Initial acquisition beta | Initial runtime default | YAML may declare finite non-negative `runtime_defaults.acquisition.beta`; default remains `2.0`. |
| Initial active bounds | Initial runtime default | Optional public domain restriction inside original public domain. Distinct from immutable dataset domain and from temporary suggestion bounds. Autonomous profile currently cannot revise persistent bounds after start. |
| Initial objectives/constraints | Initial runtime defaults | Keep minimum schema aligned with current implementation: one target/direction and empty constraints. Avoid duplicate YAML fields until multi-objective/constraints are actually supported. |
| Runtime acquisition revisions | Runtime-adjustable | Generated Frame state/event log; requires rationale, increments configuration revision. |
| Runtime persistent bounds/objective/constraint revisions | Runtime-adjustable, profile-gated | Generated Frame state/event log. Default profile exposes them; autonomous omits them. These change effective runtime configuration but not the original YAML/hash. |
| Suggest `bounds`, `around`, `radius`, per-call acqf/beta | Runtime-adjustable temporary settings | Per-tool-call, never copied into immutable config or active bounds. Temporary bounds intersect with active bounds and cannot widen them. |
| Candidate inspection filters/cursor/limit | Runtime-adjustable temporary settings | Per-call read-only controls; generated tool trace only. |
| Campaign UUID/study UUID | Generated state | Created at init. Must not be authored or reused from YAML. |
| Features/categories/original domain | Generated state | Derived from public train/candidate files. YAML must not duplicate them. |
| Trials, receipts, metrics, event log, state/config revisions | Generated state | Runtime truth and recovery data; never accepted as YAML input. |
| Dataset summary, TASK.md, CAMPAIGN.md | Generated audit/context outputs | Derived label-free artifacts. Hash/source relationships should point to input config and public inputs. |
| `manifest.json` | Generated immutable campaign manifest | Materialized per campaign from YAML plus generated campaign ID and prior audit. Include source-config relative identity/hash and normalized selected run values. Never hand-edit. |
| `campaign-run-config.json` | Generated audit-only output | Append-only effective runtime/provider/prompt/code/leakage revisions. Include declared config hash plus effective config hash; never use it as an input on a fresh run. |
| `frame/state.json` | Generated mutable state | Effective campaign/runtime state and recovery source. Keep original YAML hash/provenance reference, not the whole YAML if secrets/path leakage could result. |
| Prompt/system/reference/code/prior hashes | Audit-only output | Generated SHA-256 hashes of exact bytes/effective normalized values. |
| `.receipt-key`, `OPENAI_API_KEY`, other credentials | Environment secret | Never allowed in YAML, manifest, campaign-run-config, Frame, prompt, error snapshot, or hash input that could permit secret confirmation. Unknown secret-looking keys should fail like all unknown keys. |
| `test.csv`, hidden labels, global optimum, candidate rankings, label-derived statistics | Hidden benchmark data | Forbidden in YAML and all pre-commit/model-visible/audit configuration. Oracle alone may read labels after exact commitment; reports may use hidden results only in explicitly post-run benchmark analysis, never to construct input config. |

## Minimum YAML shape

```yaml
schema_version: 1
experiment:
  name: suzuki-autonomous-agent
  dataset: ../../datasets/chemical_reactions/suzuki
  output: ../../runs/suzuki/autonomous-agent-bo
  policies: [default, autonomous_agent]
  seeds: [300, 301, 302, 303, 304]
  budget: 2
  objective:
    target: Yield
    direction: maximize
runtime:
  provider: ai-modeling
  model: gpt-5.6-sol
  thinking: xhigh
  defaults:
    acquisition:
      name: noisy_logei
      beta: 2.0
```

Deliberately omitted: campaign/study IDs, features/categories, candidate values, temporary bounds, receipts, outcome fields, prompt hashes, code hash, config hash, credentials, provider generation seed, global-best data, and report thresholds. Add optional initial persistent bounds only when a real reproducibility case needs them; do not add speculative per-policy overrides or an inheritance system.

## Validation and loading path

1. Add one Python owner for the YAML schema and normalization, using already-installed Pydantic. Add PyYAML only if no existing YAML parser is available at implementation time; otherwise reuse the existing dependency. The loader reads raw YAML as untrusted input, requires a mapping root, validates strict models with unknown keys forbidden at every level, and emits normalized plain data.
2. Resolve `dataset` and `output` relative to the YAML file directory, not process CWD. Preserve the authored relative strings in provenance and separately record normalized resolved paths only in local generated artifacts that already require them. Reject ambiguous/nonexistent dataset input and output collisions before creating any campaign directory.
3. Compute `source_config_hash` from the exact YAML bytes and `normalized_config_hash` from canonical JSON of the validated normalized public data. Exact-byte hash proves the file; normalized hash compares semantics independent of comments/formatting.
4. Deterministically expand policies × seeds in author order into campaign run records. Each generated record receives the same immutable experiment values and its selected policy/seed/output.
5. Route each record through existing `boagent init` and `boagent run` behavior (shared Python functions or subprocess contract), not a parallel campaign creator. Existing commands/flags stay operational when no config is supplied.
6. Config-backed execution must validate the whole plan and leakage safety before creating directories or starting a provider. Runtime acquisition defaults are applied to Frame before provider startup and are recorded as initialization, not a synthetic agent revision.
7. Generated `manifest.json` records source config path as a safe relative/reference string, both hashes, normalized selected run values, and prior audit. `campaign-run-config.json` records the same declared config hash plus effective provider/model/thinking/policy and prompt/code/leakage hashes. `frame/state.json` records the declared config hashes and initial/effective runtime configuration revisions.
8. Resume uses generated campaign state, verifies its declared config hash against the supplied config if one is supplied, and refuses mismatch. Do not silently regenerate or merge config into non-empty state.

## CLI compatibility and precedence

- Preserve `boagent init --dataset-root ... --output ... [--seed ...] [--budget ...] [--target ...] [--direction ...]` unchanged for ad-hoc campaigns.
- Preserve `boagent run --campaign ... [--model ...] [--thinking ...] [--policy ...]` unchanged; omitted policy remains `default`.
- Add one config-backed experiment entry point at the current experiment planning boundary, e.g. `boagent experiment --config path.yaml [--plan]`, or expose the existing benchmark planner as a supported command. It validates/prints the deterministic expanded plan and then runs existing init/run pathways. Do not overload every existing flag with YAML precedence rules.
- For a config-backed experiment, YAML owns all declared values. Avoid arbitrary CLI overrides: they make the public config insufficient for reproduction. Operational flags such as `--plan`/dry-run and explicit resume may exist but must not alter experiment semantics.
- Environment is consulted only for secrets and currently supported operational fallback where unavoidable. Secret environment variables never override public experiment semantics. If legacy `BOAGENT_MODEL` remains for direct Supervisor invocation, config-backed orchestration passes model explicitly so YAML wins.

## Leakage and secret safety

- Strict unknown-key rejection prevents misspellings and prevents smuggling undeclared secret/hidden fields.
- Reject keys or schema sections for labels, global optimum, rankings, candidate scores, result thresholds derived from hidden labels, receipt keys, API keys, tokens, or arbitrary environment maps.
- Do not hash secrets into public audit records. A hash of a low-entropy or known secret candidate can itself leak confirmation.
- The config hash covers public declarative input only. Prior content retains its existing separate hash/scan/provenance fields.
- Extend leakage preflight input with the normalized model-visible subset and config provenance; continue allowlist construction rather than spreading normalized config or manifest objects.
- Error messages may name the invalid field path but must not echo secret-looking values or entire YAML payloads.

## Observable acceptance criteria for the planning artifacts

1. A checked-in sample YAML alone determines the same deterministic policy × seed campaign plan, including dataset/output, budget, objective, provider/model/thinking, and initial acquisition defaults.
2. Relative dataset/output paths resolve against the config file directory and produce the same normalized plan from any working directory.
3. An unknown key, unsupported schema version/policy/direction/acquisition, duplicate seed/policy, non-positive budget, non-finite/negative beta, nonexistent dataset input, or existing output campaign directory fails before campaign creation/provider startup.
4. Existing `boagent init` and `boagent run` invocations behave as before when no config is used; omitted `--policy` remains `default`.
5. Config-backed execution creates each campaign through the existing initialization/run path; it does not maintain a second implementation of manifest/Frame creation.
6. `manifest.json` contains the selected immutable campaign values and source/normalized config hashes; `campaign-run-config.json` contains effective provider/prompt/code/leakage audit plus the declared config hash; Frame contains generated mutable state and points to declared provenance.
7. Agent/runtime changes to acquisition and other exposed controls update generated configuration revision/events without rewriting the YAML or declared hash.
8. Temporary bounds/filter/radius controls affect only the current tool call, narrow active bounds, and never become immutable input or persistent state.
9. Credentials and receipt keys are accepted only from environment/local generated secret files and are absent from YAML, hashes, generated public audit JSON, model-visible context, and error output.
10. Hidden labels, global optimum, candidate rankings, and label-derived statistics are rejected from input and remain unavailable pre-commit; existing leakage preflight still runs before provider startup.
11. Provider generation remains explicitly recorded as unseeded/unavailable; reproducibility claims are limited to declared inputs, code/config/prompt hashes, traces, and outcomes, not byte-identical model responses.
12. Resuming with a supplied config whose hash differs from the campaign's declared config fails closed rather than merging or silently overriding state.

## Recommended scope boundaries

### In scope

- One strict versioned YAML schema.
- Deterministic multi-campaign plan expansion.
- Existing CLI compatibility.
- Central load/validation/normalization.
- Provenance hashes and relationships among YAML, manifest, run audit, and Frame.
- Runtime default versus runtime mutation semantics.
- Leakage/secret exclusions.

### Out of scope

- General config inheritance/includes/templates.
- Per-policy or per-seed arbitrary override trees.
- Embedding candidate domains or datasets in YAML.
- Multi-objective or non-empty constraint support not already implemented.
- Provider credential management.
- Claiming provider-output replayability.
- Using hidden benchmark statistics to set input parameters.

## Settled product decision

YAML schema version 1 is matrix-only: it expands the declared policies × seeds with shared immutable settings. Arbitrary per-run/per-arm overrides are out of scope because they would weaken matched comparison semantics and add unnecessary schema, precedence, hashing, and audit complexity.
