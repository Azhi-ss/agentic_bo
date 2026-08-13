from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import torch
from botorch.acquisition import UpperConfidenceBound, qLogNoisyExpectedImprovement
from botorch.acquisition.analytic import LogExpectedImprovement
from botorch.fit import fit_gpytorch_mll
from botorch.models import MixedSingleTaskGP
from botorch.models.transforms import Standardize
from gpytorch.mlls import ExactMarginalLogLikelihood
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold

from .state import Study

DTYPE = torch.double


@dataclass
class FittedSurrogate:
    model: MixedSingleTaskGP
    train_x: torch.Tensor
    train_y: torch.Tensor


def encode_frame(frame: pd.DataFrame, study: Study) -> torch.Tensor:
    columns = []
    for feature in study.features:
        mapping = {str(value): i for i, value in enumerate(study.categories[feature])}
        encoded = frame[feature].map(lambda value: mapping[str(value)])
        if encoded.isna().any():
            raise ValueError(f"unknown category in {feature}")
        columns.append(encoded.to_numpy(dtype=float))
    return torch.tensor(np.column_stack(columns), dtype=DTYPE)


def _fit_surrogate_model(train_x: torch.Tensor, train_y: torch.Tensor) -> MixedSingleTaskGP:
    model = MixedSingleTaskGP(
        train_X=train_x,
        train_Y=train_y,
        cat_dims=list(range(train_x.shape[1])),
        outcome_transform=Standardize(m=1),
    )
    fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
    return model


def fit_surrogate(study: Study, candidates: pd.DataFrame) -> FittedSurrogate:
    rows: list[dict[str, Any]] = []
    values: list[float] = []
    sign = 1.0 if study.direction == "maximize" else -1.0
    for item in study.initial:
        rows.append({feature: item[feature] for feature in study.features})
        values.append(sign * float(item[study.target]))
    for trial in study.all_observed:
        rows.append(trial.config)
        values.append(sign * float((trial.metrics or {})[study.target]))
    train_x = encode_frame(pd.DataFrame(rows), study)
    train_y = torch.tensor(values, dtype=DTYPE).unsqueeze(-1)
    model = _fit_surrogate_model(train_x, train_y)
    return FittedSurrogate(model=model, train_x=train_x, train_y=train_y)


def posterior_rows(fitted: FittedSurrogate, x: torch.Tensor, direction: str) -> tuple[np.ndarray, np.ndarray]:
    with torch.no_grad():
        posterior = fitted.model.posterior(x)
    sign = 1.0 if direction == "maximize" else -1.0
    mean = sign * posterior.mean.squeeze(-1).cpu().numpy()
    variance = posterior.variance.squeeze(-1).cpu().numpy()
    return mean, variance


def acquisition_values(
    fitted: FittedSurrogate,
    x: torch.Tensor,
    acqf: str,
    beta: float,
) -> np.ndarray:
    if acqf == "noisy_logei":
        acquisition = qLogNoisyExpectedImprovement(fitted.model, X_baseline=fitted.train_x)
        values = acquisition(x.unsqueeze(1))
    elif acqf == "logei":
        best = fitted.train_y.max()
        acquisition = LogExpectedImprovement(fitted.model, best_f=best)
        values = acquisition(x.unsqueeze(1))
    elif acqf == "ucb":
        acquisition = UpperConfidenceBound(fitted.model, beta=beta)
        values = acquisition(x.unsqueeze(1))
    else:
        raise ValueError(f"unknown acqf: {acqf}")
    return values.detach().cpu().numpy().reshape(-1)

def ranked_candidate_positions(scores: np.ndarray, q: int) -> np.ndarray:
    return np.argsort(-scores, kind="stable")[:q]

def diverse_candidate_positions(scores: np.ndarray, x: torch.Tensor, q: int) -> np.ndarray:
    if q <= 1:
        return ranked_candidate_positions(scores, q)
    chosen = [int(np.argmax(scores))]
    distances = torch.cdist(x, x).cpu().numpy()
    while len(chosen) < min(q, len(scores)):
        remaining = [index for index in range(len(scores)) if index not in chosen]
        scale = max(float(np.ptp(scores)), 1.0)
        next_index = max(remaining, key=lambda index: float(scores[index]) + scale * min(distances[index, selected] for selected in chosen))
        chosen.append(next_index)
    return np.array(chosen, dtype=int)


def _cross_validated_r2(train_x: torch.Tensor, train_y: torch.Tensor) -> tuple[float | None, str]:
    if len(train_y) < 3:
        return None, "insufficient_data"
    predicted = np.empty(len(train_y))
    try:
        for train_indices, test_indices in KFold(n_splits=min(5, len(train_y))).split(train_x):
            model = _fit_surrogate_model(train_x[train_indices], train_y[train_indices])
            with torch.no_grad():
                predicted[test_indices] = model.posterior(train_x[test_indices]).mean.squeeze(-1).cpu().numpy()
        score = float(r2_score(train_y.squeeze(-1).cpu().numpy(), predicted, force_finite=False))
        return (score, "ok") if np.isfinite(score) else (None, "constant_target")
    except Exception:
        return None, "fit_failed"


def _sensitivity_analysis(model: MixedSingleTaskGP, study: Study, train_x: torch.Tensor) -> dict[str, float]:
    """First-order sensitivity proxy per dimension for a (categorical) GP.

    For each training point, vary each dimension across all of its domain
    levels while holding the other dimensions at the point's value, then take
    the standard deviation of the posterior mean across those variations.
    A dimension whose levels leave the response roughly unchanged gets a small
    value; one whose levels swing the response dominates. Averaged over the
    training data. Constant dimensions (a single level) report 0.0.

    NOTE: autograd through MixedSingleTaskGP's CategoricalKernel is not
    supported (the categorical input path is discrete), so a discrete
    finite-difference proxy is used instead of a true gradient.
    """
    if not len(train_x):
        return {feature: 0.0 for feature in study.features}
    means: dict[str, list[float]] = {feature: [] for feature in study.features}
    with torch.no_grad():
        for point in train_x:
            for dimension, feature in enumerate(study.features):
                levels = study.categories.get(feature, [])
                if len(levels) <= 1:
                    means[feature].append(0.0)
                    continue
                variations = torch.empty((len(levels),), dtype=DTYPE)
                for level_index, level in enumerate(levels):
                    probe = point.clone()
                    probe[dimension] = float(level_index)
                    variations[level_index] = model.posterior(probe.unsqueeze(0)).mean.squeeze(-1).item()
                means[feature].append(float(variations.std().item()))
    return {feature: float(np.mean(values)) for feature, values in means.items()}


def diagnostics(fitted: FittedSurrogate, study: Study) -> dict[str, Any]:
    with torch.no_grad():
        predicted = fitted.model.posterior(fitted.train_x).mean.squeeze(-1).cpu().numpy()
    actual = fitted.train_y.squeeze(-1).cpu().numpy()
    covar = fitted.model.covar_module
    lengthscale = getattr(covar, "base_kernel", covar).lengthscale.detach().cpu().reshape(-1).tolist()
    noise = float(fitted.model.likelihood.noise.detach().cpu().item())
    cv_r2, cv_r2_status = _cross_validated_r2(fitted.train_x, fitted.train_y)
    return {
        "objective": study.target,
        "n_observed": len(actual),
        "train_r2": float(r2_score(actual, predicted)) if len(actual) > 1 else None,
        "cv_r2": cv_r2,
        "cv_r2_status": cv_r2_status,
        "noise": noise,
        "lengthscales": dict(zip(study.features, lengthscale, strict=False)),
        "sensitivity": _sensitivity_analysis(fitted.model, study, fitted.train_x),
    }
