# Technical design

## Architecture and boundary

Introduce one `ExperimentConfig` loading boundary above the existing campaign commands:

```text
human YAML
  -> strict parse + validation
  -> normalized public config + hashes
  -> deterministic policy × seed run plan
  -> existing campaign initialization
  -> existing campaign Supervisor run
  -> generated manifest / Frame / run audit / trajectory
```

The experiment config owns declared intent. The existing campaign artifacts retain separate roles:

- `manifest.json`: generated per-campaign immutable materialization and provenance;
- `frame/state.json`: generated mutable optimization/trial state and recovery source;
- `campaign-run-config.json`: generated effective provider/prompt/code/leakage audit revisions;
- trajectory/receipts/status: generated execution evidence.

Do not make any generated artifact a second editable input format.

## Proposed public YAML v1

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

V1 is matrix-only: expand the declared policy list × seed list with shared settings. Reject arbitrary per-run/per-arm overrides. Do not add inheritance, includes, implicit defaults that vary by policy, or embedded domain data.

## Schema contract

Use strict Pydantic models with `extra="forbid"` at every object level. Required validation:

- root is a mapping;
- `schema_version == 1`;
- non-empty stable experiment name;
- dataset/output are non-empty paths;
- policies and seeds are non-empty and unique;
- policies are currently `default|autonomous_agent`;
- seed values are integers;
- budget is positive;
- target is non-empty;
- direction is `maximize|minimize`;
- provider/model/thinking are non-empty and provider is supported;
- acquisition is one of current Frame acquisitions;
- beta is finite and non-negative.

Unknown keys fail. Never accept credentials, arbitrary environment maps, labels, global-best fields, candidate rankings/scores, receipts, metrics, or generated IDs.

## Path semantics

Resolve authored dataset/output paths relative to the YAML file's parent directory. Normalized semantic data carries POSIX-normalized authored relative references plus resolved runtime `Path` objects separately.

- Exact source bytes retain comments/formatting for `source_config_hash`.
- Canonical normalized public values produce `normalized_config_hash`.
- Running from a different CWD must not change either expanded plan semantics or output destinations.
- Generated model-visible data never receives absolute paths.

## Data flow and precedence

### Config-backed experiment

1. Read exact bytes and compute SHA-256 source hash.
2. Parse YAML, validate strictly, normalize semantic values, compute canonical normalized hash.
3. Resolve paths and validate the complete dataset/plan.
4. Expand policies × seeds in authored order.
5. Verify every campaign output is absent before creating any output.
6. Materialize each campaign through the existing initialization path.
7. Apply declared initial acquisition defaults before provider startup.
8. Run the existing Supervisor with explicit policy/provider/model/thinking values.

YAML wins for all public experiment semantics. CLI only selects operational behavior such as plan/dry-run, execute, or explicit resume. Environment supplies secrets. Direct Supervisor environment fallback must not override values explicitly passed by config-backed orchestration.

### Existing commands

Keep current direct commands unchanged:

- `boagent init --dataset-root ... --output ... [--seed ...] [--budget ...] [--target ...] [--direction ...]`
- `boagent run --campaign ... [--model ...] [--thinking ...] [--policy ...]`

Omitted policy remains `default`. These commands remain the minimum ad-hoc single-campaign interface.

## CLI entry point

Recommended minimal entry point:

```text
boagent experiment --config path.yaml --plan
boagent experiment --config path.yaml
```

`--plan` prints normalized public config hashes and the deterministic expanded commands/outputs without creating directories or starting providers. The execute form reuses the existing init/run implementation.

Avoid accepting semantic overrides beside `--config`; otherwise the YAML is not sufficient to reproduce the plan. If resume is needed, make it explicit and require config-hash equality with generated campaign provenance.

## Runtime defaults versus autonomous freedom

Initial acquisition function/beta are starting values. They are applied before the first model turn and recorded as initialization. Existing profile-authorized runtime behavior remains:

- acquisition/beta may be revised with rationale and configuration revision;
- default profile may expose persistent bounds/objective/constraint revisions;
- autonomous profile omits permanent bounds/objective/constraint tools but retains acquisition control;
- temporary suggestion bounds/around/radius and candidate filters remain per-call and are never persisted as declared config;
- temporary bounds intersect with active bounds and cannot widen the public domain.

The YAML must not prescribe agent tool order, candidate rankings, selected candidates, or hidden-result-dependent stopping choices.

## Provenance relationship

### `manifest.json`

Add generated fields equivalent to:

```json
{
  "experiment_name": "suzuki-autonomous-agent",
  "experiment_policy": "default",
  "source_config": "relative/safe/reference.yaml",
  "source_config_hash": "sha256",
  "normalized_config_hash": "sha256",
  "seed": 300,
  "budget": 2,
  "target": "Yield",
  "direction": "maximize",
  "initial_runtime": {"acqf": "noisy_logei", "beta": 2.0}
}
```

Keep current generated campaign ID, local dataset path, and prior audit metadata. Only an allowlisted subset may enter prompts.

### `campaign-run-config.json`

Each effective revision retains current provider/model/thinking/policy and prompt/reference/code/prior/leakage hashes, and adds the declared normalized config hash. Its own effective `config_hash` continues to cover the actual run audit. Do not use this file to reconstruct a fresh declared experiment.

### `frame/state.json`

Record declared config hashes and initial acquisition provenance. Frame remains the mutable truth for current effective acquisition, bounds, objectives, constraints, trials, and revisions. Runtime revision events must point back to the prior effective values; they do not alter the declared hash.

## Leakage and secret boundary

- YAML cannot contain secret fields or arbitrary environment mappings.
- API keys and receipt key remain environment/local secret-file inputs.
- Neither config hash includes secrets.
- Strict unknown-key rejection blocks accidental hidden/secret fields.
- Error output identifies paths, not full payload/value dumps.
- Extend leakage preflight with only safe experiment name/policy/hash fields.
- Do not spread normalized config, manifest, or Frame objects into model context.
- Hidden labels/global optimum/rankings never appear in YAML or pre-commit artifacts. Oracle remains the post-commit label boundary.

## Compatibility and migration

- No migration is required for existing direct CLI users or existing campaign directories.
- Config provenance fields added to generated JSON are additive; state loading must default them for older campaigns.
- Existing hardcoded experiment constants can be replaced only after a checked-in YAML covers the current Suzuki matrix and the plan output matches the current contract.
- Existing campaign directories remain resumable without a YAML under current direct commands. If a YAML is supplied during resume, require hash equality.

## Failure behavior

Fail before any campaign creation/provider startup on:

- YAML syntax/root/schema errors;
- unknown or forbidden keys;
- invalid enums/numbers/duplicates;
- missing or incompatible dataset public inputs;
- output collision anywhere in expanded plan;
- normalized/hash mismatch during config-backed resume;
- leakage-preflight failure.

Preserve created campaign evidence after runtime/provider failures; do not delete failed directories or replace seeds.

## Trade-offs

- Strict matrix-only v1 is the settled product boundary. It exactly fits the current experiment, keeps matched-arm semantics inspectable, and avoids per-run precedence rules.
- Two hashes are slightly more data than one, but distinguish exact-file provenance from semantic equivalence.
- Keeping manifest, Frame, and run audit separate avoids a large overloaded configuration/state file and preserves current recovery/audit responsibilities.

## Rollback

Remove the config-backed experiment entry point, schema/loader, and additive provenance fields. Existing `boagent init`, `boagent run`, generated campaign artifacts, and hardcoded planner remain independently usable until final cutover is verified.
