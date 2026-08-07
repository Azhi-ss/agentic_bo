# The lenz Toolkit

This is SARA's command reference. `SYSTEM.md` says when to use each move. This file says what each command does.

Call lenz through shell.

Every command:

- takes `--state ./state.json`;
- prints one JSON line;
- returns either `{"ok": true, "command": "...", "result": ...}` or `{"ok": false, "command": "...", "error": "..."}`.

Always parse the response. On `ok: false`, read `error` and fix the call.

JSON arguments are passed as single-quoted JSON strings:

```bash
--config '{"x1": 1.0, "x2": 2.0}'
```

## Create

Use `create` to define the search space, objectives, constraints, and acquisition function.

```bash
lenz create --state ./state.json \
  --space '{"x1":{"kind":"range","lower":1,"upper":5},
             "x2":{"kind":"range","lower":4,"upper":100,"step":4,"type":"int"},
             "c1":{"kind":"choice","values":["white","black","green"]}}' \
  --objectives '{"loss":"minimize"}' \
  --constraints '[{"metric":"latency","upper":100}]' \
  --acqf noisy_logei
```

Space entries:

- `kind: "range"` requires `lower` and `upper`;
- range may include `step`, `type: "float" | "int"`, and `log_scale`;
- `kind: "choice"` requires `values` and may include `ordered`.

Objectives:

- map metric name to `"minimize"` or `"maximize"`;
- one objective means single-objective BO;
- two or more objectives means multi-objective BO.

After create, check `result.space` against the intended problem.

Ask the human before create if objective direction, bounds, types, metric names, constraints, evaluation command, or budget are unclear.

## Suggest

Use `suggest` to propose candidate configs. It is a pure read and records nothing.

```bash
lenz suggest --state ./state.json
lenz suggest --state ./state.json --q 4
```

Returns candidates:

```json
[
  {
    "config": {"x1": 1.2},
    "acquisition_values": {"logei": -3.1},
    "acqf": "logei"
  }
]
```

Warm-up behavior:

- before enough observations exist, `suggest` returns Sobol space-filling candidates;
- after enough observations, it switches to the configured model acquisition function.

Use `--q N` for true batch or parallel evaluation, or as a menu when comparing options. A suggested candidate is not committed until submitted.

For `logei` and `noisy_logei`, the reported value is log(EI). A negative value means EI < 1; it does not mean negative improvement, zero improvement, or convergence.

## Submit

`submit` commits the exact config you are about to evaluate and marks it in-flight (later `suggest` calls won't duplicate an in-flight config). It has two forms:

```bash
# in-flight only — dispatch the evaluation now, complete it later with observe:
lenz submit --state ./state.json --config '{"x": 1.0}'
# one call — when you already hold the metrics, record as observed immediately:
lenz submit --state ./state.json --config '{"x": 1.0}' --metrics '{"loss": 0.42}'
```

Use the in-flight form when the result returns later (async/parallel), and the one-call form when you already have the result (synchronous).

## Observe

`observe` completes an in-flight config — one you already `submit`ted — by attaching its metrics:

```bash
lenz observe --state ./state.json --config '{"x": 1.0}' --metrics '{"loss": 0.42}'
```

**`observe` requires a matching prior `submit`.** The config must exactly match one currently in-flight. On a config you never submitted, `observe` records nothing and returns `ok: false` (listing the outstanding submitted configs) — it does not create a trial. So every `observe` is paired with an earlier `submit` of the same config. If you already have the metrics and never submitted, use the one-call `submit --config --metrics` instead.

## The three verbs — keep them straight

- `suggest` proposes (a free read, records nothing)
- `submit` commits a config as in-flight
- `observe` completes an in-flight config with its metrics.

A real evaluation reaches lenz only when it ends up **observed** — via `observe` after a `submit`, or via the one-call `submit --config --metrics`. A `suggest` call, a loop iteration, and an `observe` with no prior `submit` all record nothing.

## The evaluation loop

```text
setup:
  create or load ./state.json

repeat until the budget of real evaluations is spent:
  choose the next config — from suggest, from score-ing your own candidates against lenz's, or a point you trust
  submit the exact config (in-flight) and run the real experiment
  observe that config with its real metrics when the result returns to update lenz posterior
  (synchronous shortcut: collapse submit+observe into one call, submit --config --metrics)
  interpret the result before choosing the next config

finish:
  reconcile with lenz status — nothing left in-flight (submitted but never observed), or that dispatched evaluation's result was dropped;
  then report the incumbent (or Pareto front)
```

Check `ok` on every call. Never discard lenz output (e.g. piping to `/dev/null`) inside a loop — a silently failed `submit`/`observe` records nothing, stalls the posterior, and costs you that evaluation.

## Running The Experiment

lenz proposes `x`. The experiment returns `y`.

Example:

```bash
python3 evaluate.py '<config-json>'
```

The experiment output must be real metrics JSON compatible with the objective and constraints.

Never pass lenz predictions to `submit` or `observe`.

## Temporary Search Steering

### `suggest --bounds`

Use for a one-call region restriction.

```bash
lenz suggest --state ./state.json \
  --bounds '{"x1":[0,2],"x2":[10,20]}'
```

Use this for context-derived or trial-history-derived regional priors. Bounds must stay inside the original domain. This does not persist.

### `suggest --around`

Great tool for local refinement near the current incumbent.

```bash
lenz suggest --state ./state.json --around --radius 0.1
```

`--radius` is a fraction of each domain width in `(0, 1]`. Log-scale dimensions use log-width. Choice parameters are pinned at the incumbent.

Use per-dimension local refinement when only selected knobs should move and you want to pin the rest based on your prior or own exploration.

After consecutive local refinements along one dimension, compare an under-explored region unless quantified acquisition and posterior uncertainty rule it out.

```bash
lenz suggest --state ./state.json \
  --around '{"lr":0.1,"dropout":{"fix":0.0},"optimizer":["adam","adamw"]}'
```

In a per-dimension spec:

- a number means radius for that dimension;
- `{"fix": value}` pins the dimension;
- a list restricts a choice parameter;
- omitted dimensions are pinned at the incumbent.

## Persistent Search Steering

### `set-bounds`

Persistently shrink the active search domain.

```bash
lenz set-bounds --state ./state.json \
  --bounds '{"x":[0,5]}'
```

Use only after evidence and/or strong prior support making the region the new working domain. For one-off probes, prefer `suggest --bounds`.

### `set-acqf`

Change the acquisition function.

```bash
lenz set-acqf --state ./state.json --acqf logei
lenz set-acqf --state ./state.json --acqf ucb --beta 2.0
lenz set-acqf --state ./state.json --acqf sobol
```

Common choices:

- `noisy_logei`: default single-objective acquisition. Integrates over observation noise, so it doesn't over-commit to lucky-high observations. Use it whenever the objective is not fully deterministic.
- `logei`: cheaper alternative for deterministic objectives. Prefer noisy_logei unless you can name a specific reason the objective has no observation noise.
- `pi`: probability of improvement;
- `ucb`: tunable exploration with `--beta`;
- `sobol`: pure space-filling exploration;
- `nehvi` or `ehvi`: multi-objective acquisition; the first is the noisy variant.

Use exploratory acquisition or Sobol when diagnostics indicate the model is unreliable.

### `set-objectives`

Change objectives without losing data.

```bash
lenz set-objectives --state ./state.json \
  --objectives '{"loss":"minimize","throughput":"maximize"}'
```

One objective is single-objective. Two or more objectives produce a Pareto problem.

### `set-constraints`

Set or update outcome constraints.

```bash
lenz set-constraints --state ./state.json \
  --constraints '[{"metric":"latency","upper":100.0}]'
```

Constraints can use `upper`, `lower`, or both.

### `status`

Inspect current state shape.

```bash
lenz status --state ./state.json
```

Use this to verify objectives, constraints, acquisition, bounds, and trial counts.

## Reading The Model

### `diagnostics`

```bash
lenz diagnostics --state ./state.json
```

Use after enough observations exist.

Important fields:

- `train_r2`: in-sample fit only; keep it for diagnostics, not as evidence that predictions generalize.
- `cv_r2`: strict K-fold out-of-sample fit quality; each fold refits the surrogate. Low or negative means the surrogate is not trustworthy.
- `sensitivity`: first-order sensitivity per parameter, signed by objective direction.
- `noise`: inferred observation noise.
- `lengthscales`: GP lengthscales.

Use `cv_r2` before aggressive exploitation, narrowing bounds, or trusting sensitivity. A single Observation can only support or weaken a mechanism hypothesis; require a matched comparison or repeated experiment before claiming SAR or causality.

### `predict`

```bash
lenz predict --state ./state.json \
  --configs '[{"x":1.0},{"x":2.0}]'
```

Returns posterior means and variances for named configs.

Use for sanity checks. Do not treat predictions as results.

With constraints set, predictions also include `prob_feasible`: the model's estimated probability that all constraints hold at that config, in `[0, 1]`.

### `score`

```bash
lenz score --state ./state.json \
  --configs '[{"x":1.0},{"x":2.0}]' \
  --acqf logei
```

Ranks your own candidate configs by acquisition utility.

Use this to compare a prior-driven candidate against lenz' suggestions.

With constraints set, `score` ranks by the constrained acquisition that `suggest` optimizes; use `predict`'s `prob_feasible` when you need a human-readable feasibility probability.

Higher is better within a column. Different acquisition functions are on different scales. `logei` and `noisy_logei` report log(EI): negative means EI < 1, not negative or zero improvement and not convergence. Stop only with quantified global acquisition scale/stability, posterior uncertainty, and repeated exhaustion of distinct suggestions.

### `trials`

```bash
lenz trials --state ./state.json
```

Dumps the full trial log for analysis.

## Incumbents And Pareto Fronts

### `incumbent`

```bash
lenz incumbent --state ./state.json
```

Returns the best feasible observed point for single-objective optimization.

If persistent bounds have changed, compare global and in-bounds incumbents:

```bash
lenz incumbent --state ./state.json
lenz incumbent --state ./state.json --in-bounds
```

The global incumbent may sit outside the current active bounds.

### `pareto`

```bash
lenz pareto --state ./state.json
```

Returns the Pareto front for multi-objective optimization.

## Batch And Asynchronous Evaluation

For true parallel evaluation:

```bash
lenz suggest --state ./state.json --q 4
lenz submit --state ./state.json --config '<cfg-1>'
lenz submit --state ./state.json --config '<cfg-2>'
lenz submit --state ./state.json --config '<cfg-3>'
lenz submit --state ./state.json --config '<cfg-4>'
```

Run the evaluations in parallel. Each config is now in-flight; `observe` each result as it arrives:

```bash
lenz observe --state ./state.json --config '<cfg-1>' --metrics '<metrics-1>'
```

Every in-flight config must eventually be observed — track which are still pending and reconcile with `lenz status` before you finish, or a returned result gets dropped and that evaluation is wasted. Use `suggest --q N`, not a hand-rolled loop of independent `suggest` calls, when the evaluations will truly run in parallel.

## Common Errors

- `config matches no submitted point`: submit the exact config before observe, or use `submit --config --metrics`.
- `need observed trials`: `predict`, `score`, or `diagnostics` needs a fitted model; observe more points first.
- `unknown acqf`: fix the acquisition name.
- `not a subset of the original domain`: bounds exceed the original space.
- `radius must be in (0, 1]`: fix `--around --radius`.
- malformed JSON: quote JSON as a single shell argument.

## Command Selection Cheat Sheet

- Need first state: `create`.
- Need a candidate: `suggest`.
- Need a prior-backed region: `suggest --bounds`.
- Need local refinement: `suggest --around`.
- Need persistent narrowing: `set-bounds`.
- Need more exploration: `set-acqf --acqf ucb` with high beta or `set-acqf --acqf sobol`.
- Need to compare hand-built candidates: `score`.
- Need posterior sanity checks: `predict`.
- Need model trust evidence: `diagnostics`.
- Need trial history: `trials`.
- Need best current point: `incumbent`.
- Need multi-objective front: `pareto`.
