# Technical Design

## Architecture

Add one clean Campaign Profile boundary:

- `default`: existing Paper Prompt, automatic low-trust UCB switch, and current behavior remain unchanged.
- `autonomous_agent`: standalone autonomous prompt, no automatic acquisition switch, no precomputed suggestions in the initial prompt, label-free Candidate Inspection, and code-enforced evidence/integrity contracts.

Do not retain `lm_compare` or `lm_forced_first` as long-lived runtime policies. Preserve their completed artifacts and task record as diagnostic evidence. Reuse their additive exact-score identity fields and reporting/audit mechanisms where applicable.

## Prompt Composition

The autonomous profile uses a dedicated prompt source whose complete policy is approximately:

```text
You own the final optimization decision.

Inspect the public search space, verified historical observations, domain
context, and any typed lenz evidence you consider useful. Surrogate outputs
are non-binding advice: you may consult, accept, or override them, or proceed
without consulting ranked proposals.

Choose one legal unobserved public Candidate that you judge most valuable for
improving the Campaign. Do not access hidden Outcomes, benchmark labels,
global-best information, or label-derived statistics.

Before committing, provide the required Decision Evidence Record and finish by
committing exactly that Candidate.
```

Retain general budget, identity, black-box, receipt, and error rules, but do not import contradictory GP-first or mandatory-UCB instructions from `PAPER_SYSTEM.md`.

## Initial Context by Profile

### Default

Keep the current context path and automatic low-trust acquisition behavior.

### Autonomous

Initial context contains only:

- sanitized status fields;
- label-free dataset/search-space summary;
- current Optimization Configuration without path fields;
- no ranked suggestions or `preferred_suggestion`;
- no full historical rows;
- public domain context/prior already present in `TASK.md`.

Sara may retrieve history with `lenz_trials` and Surrogate Advice with typed tools.

Build prompt manifests with explicit allowlists. Never spread persisted manifest/Frame objects directly into model-visible JSON.

## Candidate Inspection Contract

Add a lenz command and typed Supervisor wrapper:

```text
lenz candidates --state <path> [--filters <json>] [--cursor <int>] [--limit <1..100>]
```

Response:

```json
{
  "total_matching": 42,
  "cursor": 0,
  "next_cursor": 20,
  "candidates": [
    {
      "pool_index": 123,
      "candidate_id": "...",
      "config": {}
    }
  ]
}
```

Rules:

- exact feature names and legal option values only;
- scalar or list values normalize to allowed-value filters;
- deterministic original `test_features.csv` index order;
- cursor is an offset into the filtered deterministic sequence;
- `next_cursor` is null at exhaustion;
- no label file read;
- no posterior/acquisition fields in this command;
- Supervisor counts returned rows and rejects calls exceeding 500 rows in the current Campaign Step.

## Autonomous Optimization Authority

Profile-gate the existing pre-turn low-trust acquisition switch. It remains active for `default` and inactive for `autonomous_agent`.

Autonomous allowed mutation tools:

- `lenz_set_acqf`, including `beta`.

Autonomous forbidden mutation tools:

- set bounds;
- set objectives;
- set constraints.

Prefer omitting forbidden tools from the autonomous action space instead of exposing them and rejecting later.

## Decision Evidence Record

Extend the commitment action schema with required autonomous-profile fields:

```json
{
  "hypothesis": "...",
  "evidence_sources": ["historical_observations", "domain_prior"],
  "expected_outcome": "...",
  "expected_learning": "...",
  "surrogate_relationship": "accept",
  "rationale": "..."
}
```

Validation:

- all text fields are non-empty;
- evidence sources are non-empty strings;
- relationship is one of the four declared values;
- relationship is checked against actual tool evidence:
  - `accept`: ranked proposals consulted and committed Candidate was offered;
  - `override`: ranked proposals consulted and committed Candidate was not the accepted Proposal;
  - `informed_without_proposal`: diagnostics/predict/score consulted but no ranked proposal call;
  - `not_consulted`: no Surrogate Advice tool call in the step.

The Supervisor records actual tool-use facts separately; mismatched self-classification is rejected for correction.

## Invalid Action and Stop Semantics

- Candidate identity continues to require exact `pool_index` plus `config` agreement.
- Invalid/non-pool/observed Candidates use existing capped action retries and do not call submit or Oracle.
- No silent replacement or preferred fallback exists.
- Under `autonomous_agent` experiment runs, reject `stop_campaign` before budget exhaustion.
- Provider-transient retries remain allowed only before mutating tools/actions, preserving existing state rules.

## Leakage Gate

Add a deterministic preflight used by tests and the experiment runner before provider startup.

Inspect:

- rendered first-turn prompt;
- autonomous custom-tool names and JSON schemas;
- representative sanitized initial context/tool results;
- runtime tool/resource flags;
- prior text and provenance metadata.

Forbidden prompt/result content includes:

- `dataset_root`, `public_root`, `test.csv`;
- absolute dataset paths;
- `global_best`, hidden rank/distance;
- uncommitted Outcome fields or label-derived Candidate statistics.

The gate verifies builtin tools and all extension/context/skill/template loading remain disabled. Oracle source isolation is also covered by focused code-contract tests.

Prior audit metadata belongs in run configuration evidence:

```json
{
  "prior_hash": "...",
  "prior_source": "PRIOR.md",
  "prior_scan": "label_free",
  "prior_provenance": "mechanism_or_pre_experiment_source"
}
```

## Experiment and Reporting

Fresh output root, distinct from the completed diagnostic experiment:

```text
runs/suzuki/autonomous-agent-bo/
  default/seed-300..304/
  autonomous_agent/seed-300..304/
  report.json
```

Run default and autonomous campaigns from the same source revision. Do not overwrite existing directories. Preserve failures.

Report behavior, outcomes, and integrity as separate sections. Tool-use counts should be per step as well as per run. Candidate diversity should include unique first-step and all-step Candidate counts/configs. Outcome aggregates include mean, median, and minimum, but remain descriptive.

## Compatibility and Clean Cutover

- Omitted policy remains `default`.
- Existing state and trajectory schemas remain readable; new evidence fields are additive.
- Remove the diagnostic `lm_compare`/`lm_forced_first` CLI/runtime selectors after extracting reusable mechanisms.
- Keep completed diagnostic runs and the previous task record untouched.
- Existing Paper Prompt content is not modified for the autonomous profile.

## Risks

- Autonomous Sara may ignore useful Surrogate Advice. This is a measured behavior, not a harness failure.
- Candidate inspection can consume context. Enforce deterministic pagination and the agreed row budget.
- Natural-language prior provenance cannot be proved by regex alone. Require both scan and declaration.
- Provider generation is not seed-replayable. Record the limitation and retain complete traces/hashes.
- Five seeds on Suzuki are descriptive only.

## Rollback

Remove the `autonomous_agent` profile, Candidate Inspection command/tool, leakage preflight, and experiment runner/report fields. Default policy and existing campaign artifacts remain usable.
