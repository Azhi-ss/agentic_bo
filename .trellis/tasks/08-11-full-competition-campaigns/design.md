# Design — Full competition campaigns

## Architecture and boundaries

Keep the existing pipeline. Add one flag at the orchestration edge; do not change campaign internals.

```text
competition YAML
  -> boagent experiment --resume
       -> missing campaign: existing initialize_campaign()
       -> existing campaign: strict config/state/provenance validation
       -> terminal valid campaign: skip
       -> partial valid campaign: existing run_campaign()
  -> Supervisor Frame/session/receipt reconciliation
  -> boagent package-competition (existing full contract gate)
  -> evaluation.validate_trajectory + narrow aggregate report
```

## Resume contract

`boagent experiment --config <yaml> --resume` loads the config with output-collision preflight disabled, then handles each authored run sequentially.

For an existing campaign, validate before invoking the Supervisor:

- required files: `manifest.json`, `frame/state.json`, `.receipt-key`;
- Frame dataset path, seed, budget, target, and direction equal the authored run;
- manifest campaign id equals Frame campaign id;
- manifest experiment name, policy, source config filename/hash, and normalized config hash equal the loaded config;
- Frame declared/source config hashes, source config filename, experiment name, and policy equal the loaded config;
- initial acquisition equals the authored acquisition.

A valid terminal status is left to the existing Supervisor `validateCampaignStatus` path; calling `run_campaign` is safe and exits before model/provider startup. This avoids duplicating the Node terminal-state validator in Python. A valid partial campaign also enters the same existing reconciliation path.

Default `boagent experiment` behavior is unchanged: collision preflight rejects any existing output.

## Data and leakage boundaries

- Resume validation reads only authored YAML, public dataset identity, campaign manifest, Frame, and receipt-key presence.
- Campaign decisions remain isolated behind the existing autonomous Supervisor and signed oracle receipts.
- Packaging reads Frame plus `test_features.csv`; no hidden labels.
- Post-run evaluation may read `test.csv` only after all 40-step artifacts pass packaging. Those metrics are reporting-only and never written into campaign inputs.

## Execution strategy

Run sequentially to avoid the observed provider concurrency limit:

1. Buchwald config in resume mode: seed 100 skips; seeds 200–2000 complete in order.
2. Suzuki config in resume mode: same.
3. Full package each dataset to its submission directory.
4. Validate every artifact and aggregate metrics.

The same command is the recovery procedure after interruption.

## Compatibility

- Additive CLI flag only.
- No schema, artifact, policy, prompt, oracle, or acquisition changes.
- Existing direct `init`, `run`, `experiment`, and `package-competition` calls retain their current behavior.

## Failure and rollback

- Existing campaign mismatch: stop with a field-specific error; do not mutate or delete it.
- Provider/transient interruption: preserve Frame/session/receipts and rerun the same resume command.
- Code rollback: remove the resume flag/helper and its tests. Existing campaign data remains usable via `boagent run`.
- Run artifacts are not deleted automatically.
