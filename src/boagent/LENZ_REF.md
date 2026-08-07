# The lenz Toolkit

Call lenz through shell. Every command takes `--state ./state.json`, prints one JSON line, and returns either `{ "ok": true, "command": "...", "result": ... }` or `{ "ok": false, "command": "...", "error": "..." }`. Always parse the response.

## Candidate-pool study

Create the study from the public dataset files:

```bash
uv run lenz create --state ./state.json --dataset-root DATASET_DIR --target Yield --direction maximize --seed 100
```

The create command imports `train.csv` as observed trials and `test_features.csv` as the finite candidate pool. It never reads `test.csv`.

## Suggest

```bash
uv run lenz suggest --state ./state.json --q 8
uv run lenz suggest --state ./state.json --q 8 --acqf sobol
uv run lenz suggest --state ./state.json --q 8 --acqf ucb --beta 2.0
```

`suggest` is a pure read. It returns a menu of unevaluated candidates with `query_index`, exact `config`, posterior mean/variance when available, and acquisition score. It records nothing and spends no evaluation budget.

## Submit and observe

```bash
uv run lenz submit --state ./state.json --query-index 123
uv run python -m boagent.oracle --dataset-root DATASET_DIR --query-index 123
uv run lenz observe --state ./state.json --query-index 123 --metrics '{"Yield": 53.6}'
```

- `submit` commits one exact public-pool row as in flight.
- `observe` completes that exact submitted row using real Oracle metrics.
- Never submit predictions as metrics.
- Never observe an index that is not currently in flight.

## Read the model

```bash
uv run lenz predict --state ./state.json --query-indices '[12,34]'
uv run lenz score --state ./state.json --query-indices '[12,34]' --acqf noisy_logei
uv run lenz diagnostics --state ./state.json
uv run lenz incumbent --state ./state.json
uv run lenz trials --state ./state.json
uv run lenz status --state ./state.json
```

- `predict` returns posterior moments; predictions are not observations.
- `score` compares your candidates using the current posterior.
- `train_r2` is only an in-sample fit check; interpret it together with noise and lengthscales, not as cross-validation evidence.
- `incumbent` returns the best observed candidate.
- `status` reports observed, pending, remaining candidates, objective, and acquisition configuration.

## Change acquisition

```bash
uv run lenz set-acqf --state ./state.json --acqf noisy_logei
uv run lenz set-acqf --state ./state.json --acqf ucb --beta 2.0
uv run lenz set-acqf --state ./state.json --acqf sobol
```

Supported finite-pool acquisitions: `noisy_logei`, `logei`, `ucb`, and `sobol`.

## Evaluation loop

```text
repeat until the real-evaluation budget is spent:
  explain the next learning goal
  ask lenz for a candidate menu or score your own candidates
  select exactly one query_index
  submit it
  call the Oracle once
  observe the returned real metric
  explain what changed
finish with status and incumbent
```

Every candidate identity is the stable zero-based row index from `test_features.csv`. Do not sort or renumber it. The Oracle is the only component allowed to read `test.csv`.
