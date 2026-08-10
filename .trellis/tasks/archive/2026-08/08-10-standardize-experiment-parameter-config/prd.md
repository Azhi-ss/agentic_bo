# Standardize experiment parameter configuration

## Goal

Give researchers one public, versioned, human-authored YAML file that completely declares a reproducible boagent experiment plan without revealing optimal results or constraining the agent's legitimate runtime decisions.

The YAML must replace the current hardcoded experiment-plan constants while preserving existing ad-hoc `boagent init` and `boagent run` usage. Generated campaign files remain authoritative for runtime state and audit history, but are never competing hand-authored configuration sources.

## User value

A researcher can publish the YAML with the code revision and public dataset, and another researcher can reconstruct the same campaign matrix, immutable experiment boundaries, initial runtime defaults, and audit expectations without knowing hidden labels, global optima, or candidate rankings. Provider responses may remain nondeterministic; the system records that limitation rather than overstating replayability.

## Background and confirmed facts

- `boagent init` currently accepts dataset/output, seed, budget, target, and direction, then creates `manifest.json`, public task/context files, and `frame/state.json` (`src/boagent/agent_cli.py:50-121`).
- `boagent run` currently accepts campaign, model, thinking, and policy; omitted policy remains `default` (`src/boagent/agent_cli.py:128-152`).
- Frame state mixes immutable campaign boundaries, initial optimization defaults, mutable configuration, and generated trials/events (`src/boagent/state.py:47-66`).
- Acquisition/beta and, for allowed profiles, active bounds/objectives/constraints can be revised at runtime with rationales and configuration revisions (`src/boagent/cli.py:363-455`; `supervisor/campaign.mjs:211-227`).
- Suggestion bounds/around/radius and candidate inspection filters are temporary call controls, not durable campaign configuration (`src/boagent/cli.py:91-103`; `supervisor/campaign.mjs:159-167`).
- The Supervisor writes effective model/prompt/code/prior/leakage hashes to `campaign-run-config.json` and gives the model an allowlisted effective manifest (`supervisor/supervisor.mjs:61-65,96-102,154-168`).
- Leakage preflight rejects dataset/public paths, hidden-label terms, enabled resource surfaces, and incomplete prior audit before provider startup (`supervisor/campaign.mjs:329-339`).
- The current reproducibility plan is hardcoded as policies × seeds with budget/provider/model/thinking/output/commands in `benchmark/compare.py:74-101`, contracted by `tests/test_benchmark_compare.py:83-95`.
- The archived autonomous experiment declared the same matched matrix and emphasized provider-generation-seed unavailability and leakage safety (`.trellis/tasks/archive/2026-08/08-08-autonomous-agent-bo-experiment/prd.md:69-77`; `.trellis/tasks/archive/2026-08/08-08-autonomous-agent-bo-experiment/design.md:177-190`).
- Detailed evidence and the complete parameter classification are recorded in `research/configuration-contract.md`.

## Requirements

### R1. Single human-authored input

- Define one strict, versioned YAML document as the sole human-authored input for a multi-campaign experiment plan.
- The minimum schema declares:
  - schema version;
  - stable experiment name;
  - dataset path;
  - output root;
  - non-empty supported policy list;
  - non-empty campaign seed list;
  - positive budget;
  - objective target and `maximize|minimize` direction;
  - provider, model, and thinking level;
  - initial acquisition name and beta.
- Do not duplicate generated campaign/study IDs, public feature/category topology, candidate values, trials, receipts, metrics, revisions, prompt/code hashes, or report outcomes in YAML.
- Schema version 1 is definitively matrix-only: it expands `policies × seeds` with shared immutable settings.
- Do not add per-policy/per-seed overrides, config inheritance, includes, templates, or arbitrary override trees.

### R2. Parameter ownership and mutability

The implementation must preserve these categories:

| Category | Required treatment |
|---|---|
| Immutable input | Schema/name, dataset/output roots, policies, seeds, budget, declared objective, provider/model/thinking for the reproducible plan. These values cannot change after a campaign is created. |
| Initial runtime default | Acquisition function/beta. Materialize them before the first agent turn, but allow only existing profile-authorized runtime revisions afterward. Initial persistent bounds are not part of schema version 1. |
| Runtime-adjustable | Acquisition/beta and profile-gated persistent bounds/objective/constraints, recorded in Frame revision/event history with rationale. Runtime changes never rewrite YAML or its declared hash. |
| Temporary runtime setting | Suggestion bounds/around/radius and candidate filters/cursor/limit. They affect one call, may only narrow active bounds, and never become immutable input or persistent state. |
| Generated state | Campaign/study IDs, derived domain, trials, receipts, metrics, events, and state/configuration revisions. Never accepted from YAML. |
| Audit-only output | Prompt/system/reference/code/prior/config hashes, leakage result, provider-generation-seed limitation, timestamps, and effective runtime revisions. Never used as fresh-run input. |
| Environment secret | API credentials and receipt key. Never allowed in YAML, public hashes/audits, model context, or echoed validation errors. |
| Hidden benchmark data | `test.csv`, hidden labels, global optimum, candidate rankings, and label-derived statistics. Forbidden from input and all pre-commit/model-visible configuration. |

### R3. Strict validation and canonical loading

- Use one Python schema/loader owner at the experiment boundary; reuse installed Pydantic for typed strict validation.
- Reject unknown keys at every level rather than ignoring them.
- Reject unsupported schema versions, policies, directions, acquisitions, invalid/duplicate seeds or policies, non-positive budgets, and non-finite/negative beta.
- Validate the complete experiment before creating campaign directories or starting a provider.
- Dataset/output paths are resolved relative to the YAML file, never process CWD.
- Dataset input must exist and satisfy the existing public initialization contract; every expanded campaign output must be new.
- Errors identify the invalid field path without printing the full YAML or secret-looking values.

### R4. Deterministic experiment expansion

- Expand the declared policy list × campaign seed list deterministically, preserving authored order.
- Each expanded run inherits the shared immutable settings and receives its selected policy, seed, and output directory.
- Refuse collisions rather than overwriting or silently resuming existing campaign directories.
- Provider generation seed remains explicitly `unavailable`; campaign seeds do not imply replayable provider text.

### R5. CLI compatibility and precedence

- Keep existing `boagent init` flags and behavior usable when no YAML is supplied.
- Keep existing `boagent run` flags and behavior usable when no YAML is supplied; omitted `--policy` remains `default`.
- Add one config-backed experiment entry point at the current experiment-plan/orchestration boundary, with a plan/dry-run mode that emits the normalized expanded plan without starting campaigns.
- Route config-backed campaigns through the existing initialization and run pathways; do not create a parallel manifest/Frame implementation.
- YAML owns experiment semantics in config-backed mode. CLI flags may control operations such as plan/run/resume, but must not silently override declared dataset, output, seeds, budget, objective, policy, provider, model, thinking, or initial acquisition.
- Environment supplies secrets only. Config-backed orchestration passes public runtime values explicitly so environment fallbacks cannot silently change the declared plan.

### R6. Provenance and hashes

- Compute a SHA-256 source hash over the exact YAML bytes.
- Compute a separate normalized hash over canonical JSON of the validated public semantic configuration.
- Preserve the authored path strings and record their config-file-relative meaning; use resolved absolute paths only in local generated artifacts that already require filesystem access, never in model-visible context.
- `manifest.json` records the selected immutable campaign values, safe source-config identity, both config hashes, and existing prior audit metadata.
- `campaign-run-config.json` records the declared normalized config hash plus effective provider/model/thinking/policy, prompt/system/reference/code/prior hashes, leakage result, and provider-generation-seed limitation.
- Frame state records declared config provenance and initial/effective runtime configuration without embedding secrets or making YAML contents model-visible.
- A supplied config must match the campaign's recorded declared hash on resume; mismatch fails closed instead of merging values.

### R7. Runtime acquisition and bounds semantics

- The YAML's initial acquisition name/beta are defaults, not immutable agent choices.
- Apply initial acquisition defaults before provider startup and record them as campaign initialization, not as a fabricated agent revision.
- Existing runtime acquisition changes remain profile-authorized and auditable.
- Initial persistent bounds are not part of schema version 1; existing runtime/profile-gated bounds behavior remains unchanged.
- Temporary bounds remain per-call intersections with persistent active bounds and cannot widen the domain.
- Autonomous runtime freedom remains intact: it may choose evidence/tools and acquisition revisions already permitted by its profile; the config declares boundaries and starting values, not a fixed decision sequence.

### R8. Leakage and secret exclusion

- Reject schema fields for credentials, receipt keys, arbitrary environment maps, hidden labels, global optimum, candidate rankings/scores, or label-derived thresholds.
- Do not include secrets in either config hash.
- Extend the existing allowlist/leakage-preflight path with safe config provenance only; never spread the normalized config or full manifest into prompts.
- Keep Oracle as the only pre-existing component allowed to read hidden labels after an exact commitment.
- Preserve existing prior hash/scan/provenance as a separate audit relationship; the unified config does not absorb prior contents.

## Acceptance criteria

- [ ] A public YAML determines a deterministic policy × seed campaign plan including dataset/output, budget, objective, provider/model/thinking, and initial acquisition defaults.
- [ ] Loading the same YAML from different working directories produces identical normalized semantics and output plan because relative paths resolve against the YAML file.
- [ ] Unknown keys, unsupported schema/policy/direction/acquisition, duplicate seed/policy, invalid budget/beta, missing dataset, or output collisions fail before campaign creation or provider startup.
- [ ] Existing `boagent init` and `boagent run` commands remain usable without YAML, and omitted policy remains `default`.
- [ ] Config-backed execution reuses existing campaign initialization/run behavior rather than maintaining a second manifest/Frame creator.
- [ ] `manifest.json` records selected immutable values and source/normalized config hashes; `campaign-run-config.json` records effective runtime/prompt/code/leakage audit plus declared hash; Frame records mutable generated state and declared provenance.
- [ ] Runtime acquisition or other authorized revisions update generated configuration revisions/events without changing YAML or its hashes.
- [ ] Temporary bounds/filter/radius controls remain per-call, narrow rather than widen active bounds, and never become immutable or persistent configuration.
- [ ] Credentials and receipt keys are absent from YAML, public hashes, generated audit JSON, model-visible context, and validation output.
- [ ] Hidden labels, global optimum, candidate rankings, and label-derived statistics cannot enter the input and remain unavailable before commitment; leakage preflight still runs before provider startup.
- [ ] Audits state that provider generation seeding is unavailable, so reproducibility claims cover inputs, normalized plan, code/config/prompt hashes, traces, and outcomes rather than byte-identical model responses.
- [ ] Resume with a mismatched supplied config hash fails closed without rewriting or merging existing campaign state.

## Out of scope

- Product-code implementation in this planning task.
- YAML inheritance/includes/templates.
- Arbitrary per-policy/per-seed override trees; schema version 1 is matrix-only with shared settings.
- Embedding datasets, candidate domains, historical observations, or outcomes in YAML.
- Adding multi-objective or non-empty constraint support beyond current behavior.
- Credential provisioning or secret management.
- Full provider-output replayability.
- Input parameters derived from hidden benchmark labels or optimal results.

## Technical notes

- Minimum proposed shape is documented in `research/configuration-contract.md`.
- Pydantic is already installed (`pyproject.toml:12`); a YAML parser must reuse an existing dependency if available or add only the smallest required parser during implementation.
- The clean boundary is the experiment planner currently represented by `benchmark/compare.py:78-101`, not generated `manifest.json`, `campaign-run-config.json`, or Frame state.
- Generated audit/state artifacts have separate purposes and must not be collapsed into one file.

## Key decisions

- YAML schema version 1 is matrix-only: the declared policy list is crossed with the declared seed list, and all runs share the same dataset, output-root convention, budget, objective, provider/model/thinking, and initial acquisition defaults.
- Arbitrary per-run or per-arm overrides are explicitly out of scope because they would weaken matched comparison semantics and introduce unnecessary precedence, hashing, and audit complexity.
