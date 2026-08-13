# Surrogate Architecture

> Executable contracts for deterministic local GP and BoTorch operations.

---

## Scenario: Deterministic Local GP/BoTorch RNG Isolation

### 1. Scope / Trigger

- Trigger: any local surrogate fit, diagnostic cross-validation, or stochastic BoTorch acquisition path in `src/boagent/backend.py`.
- Results depend on Campaign state and the named operation, not ambient Python, NumPy, or Torch RNG state. Concurrent local Torch fits must not corrupt one another's save/seed/restore window.

### 2. Signatures

- `local_bo_seed(study: Study, operation: str) -> int`
- `_derived_seed(seed: int, operation: str) -> int`
- `_fit_surrogate_model(train_x: torch.Tensor, train_y: torch.Tensor, seed: int) -> MixedSingleTaskGP`
- `fit_surrogate(study: Study, candidates: pd.DataFrame, operation: str = "local_bo") -> FittedSurrogate`
- `acquisition_values(fitted: FittedSurrogate, x: torch.Tensor, acqf: str, beta: float) -> np.ndarray`
- `_cross_validated_r2(train_x: torch.Tensor, train_y: torch.Tensor, seed: int) -> tuple[float | None, str]`
- `diagnostics(fitted: FittedSurrogate, study: Study) -> dict[str, Any]`

### 3. Contracts

- `local_bo_seed` hashes canonical JSON containing `study.seed`, the operation, and every initial plus observed `{config, value}` record sorted by canonical JSON. Observation arrival order does not change the seed; Campaign seed, observation content, or operation does.
- Both seed helpers use the first eight bytes of SHA-256 as an unsigned integer reduced modulo `2**63 - 1`.
- `fit_surrogate` fits with `local_bo_seed(study, f"{operation}:fit")` and stores `local_bo_seed(study, operation)` in `FittedSurrogate.seed` for acquisition-local derivation.
- `_fit_surrogate_model` encloses the full model construction and `fit_gpytorch_mll` call in `_TORCH_RNG_LOCK` plus `torch.random.fork_rng()`, then sets `torch.manual_seed(seed)`. The lock covers save, seed, fit, and restore so concurrent threads cannot restore stale global Torch state over another fit.
- Diagnostic folds call `_fit_surrogate_model` with `_derived_seed(seed, f"fold:{fold}")`.
- `noisy_logei` gives explicit derived seeds to both `SobolQMCNormalSampler` instances. `logei` and `ucb` do not consume a stochastic sampler here.
- Local BO does not seed or consume Python `random` or NumPy RNG. Direct tests require Python, NumPy, and Torch process RNG states to remain unchanged across `fit_surrogate` followed by `noisy_logei` acquisition; diagnostics stability is asserted separately across an intervening global Torch seed change.

### 4. Validation & Error Matrix

- Candidate or observation category absent from `study.categories` -> `ValueError("unknown category in <feature>")` before fitting.
- Acquisition name outside `noisy_logei`, `logei`, and `ucb` -> `ValueError("unknown acqf: <name>")`.
- Fewer than three cross-validation observations -> `cv_r2=None`, `cv_r2_status="insufficient_data"`.
- Non-finite cross-validation R² -> `cv_r2=None`, `cv_r2_status="constant_target"`.
- Diagnostic fold fit raises -> `cv_r2=None`, `cv_r2_status="fit_failed"`; this fallback applies only to the diagnostic score and does not replace a failed primary fit.
- Concurrent fits -> serialize the Torch RNG-sensitive fit window; do not use an unlocked `fork_rng` window or a process-wide permanent seed.

### 5. Good/Base/Bad Cases

- Good: identical Campaign seed, canonical observation set, and operation produce exact-equal diagnostics, posterior arrays, variances, and noisy-log-EI scores despite different ambient process seeds.
- Base: changing the operation intentionally changes its local seed while leaving caller RNG states unchanged.
- Bad: call `torch.manual_seed(study.seed)` without `fork_rng`, omit the shared lock, derive seeds from trial arrival order, or let QMC sampling consume the global Torch generator.

### 6. Tests Required

- `tests/test_backend_diagnostics.py`: set different Python/NumPy/Torch process seeds and assert equal diagnostics plus exact posterior, variance, and acquisition arrays.
- Snapshot Python, NumPy, and Torch process RNG states before `fit_surrogate` followed by `noisy_logei` acquisition and assert exact restoration afterward; test diagnostics determinism separately.
- Assert local seed stability for identical input, change for Campaign seed/observation/operation changes, and equality after reversing observed-trial arrival order.
- Force an optimizer warning/retry and assert deterministic completion plus unchanged global Torch state.
- Run diagnostics twice with an intervening global Torch seed change and assert equal result dictionaries.
- Run concurrent fits with distinct local seeds, assert each result matches its sequential baseline, and assert the caller's Torch RNG state is restored.

### 7. Wrong vs Correct

#### Wrong

```python
torch.manual_seed(study.seed)
model = MixedSingleTaskGP(train_X=train_x, train_Y=train_y, cat_dims=[0])
fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
```

#### Correct

```python
seed = local_bo_seed(study, "diagnostics:fit")
model = _fit_surrogate_model(train_x, train_y, seed)
```
