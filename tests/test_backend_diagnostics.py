import copy
import random
import unittest
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch
from botorch.exceptions.warnings import OptimizationWarning
from botorch.optim.core import OptimizationResult, OptimizationStatus

import boagent.backend as backend
from boagent.backend import acquisition_values, diagnostics, encode_frame, fit_surrogate, local_bo_seed, posterior_rows, ranked_candidate_positions
from boagent.state import Study, Trial


class BackendDiagnosticsTest(unittest.TestCase):
    def test_reports_out_of_fold_r2_separately_from_train_r2(self) -> None:
        torch.manual_seed(0)
        categories = list(range(6))
        study = Study(
            study_id="study",
            campaign_id="campaign",
            public_root=".",
            target="yield",
            direction="maximize",
            seed=0,
            budget=6,
            features=["x"],
            categories={"x": categories},
            initial=[{"x": x, "yield": value} for x, value in zip(categories, [0, 1, 4, 9, 16, 40], strict=True)],
        )

        result = diagnostics(fit_surrogate(study, pd.DataFrame({"x": categories})), study)

        self.assertIn("cv_r2", result)
        self.assertIsNotNone(result["cv_r2"])
        self.assertEqual(result["cv_r2_status"], "ok")
        self.assertNotAlmostEqual(result["cv_r2"], result["train_r2"])

    def test_reports_none_when_cross_validation_is_not_meaningful(self) -> None:
        study = Study(
            study_id="study",
            campaign_id="campaign",
            public_root=".",
            target="yield",
            direction="maximize",
            seed=0,
            budget=2,
            features=["x"],
            categories={"x": [0, 1]},
            initial=[{"x": 0, "yield": 0}, {"x": 1, "yield": 1}],
        )

        result = diagnostics(fit_surrogate(study, pd.DataFrame({"x": [0, 1]})), study)

        self.assertIsNone(result["cv_r2"])
        self.assertEqual(result["cv_r2_status"], "insufficient_data")

    def test_ucb_scores_many_candidates_after_reconfiguration(self) -> None:
        study = Study(
            study_id="study",
            campaign_id="campaign",
            public_root=".",
            target="yield",
            direction="maximize",
            seed=0,
            budget=4,
            features=["x"],
            categories={"x": [0, 1, 2, 3]},
            initial=[{"x": 0, "yield": 0}, {"x": 1, "yield": 1}, {"x": 2, "yield": 4}],
        )
        candidates = pd.DataFrame({"x": [0, 1, 2, 3]})
        fitted = fit_surrogate(study, candidates)

        scores = acquisition_values(fitted, encode_frame(candidates, study), "ucb", 2.0)

        self.assertEqual(scores.shape, (4,))

    def test_tied_acquisition_candidates_preserve_pool_order(self) -> None:
        scores = pd.Series([1.0, 1.0, 1.0, 0.5]).to_numpy()

        order = ranked_candidate_positions(scores, 3)

        self.assertEqual(order.tolist(), [0, 1, 2])

    def test_logei_scores_many_candidates(self) -> None:
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=0, budget=4, features=["x"], categories={"x": [0, 1, 2, 3]},
            initial=[{"x": 0, "yield": 0}, {"x": 1, "yield": 1}, {"x": 2, "yield": 4}],
        )
        candidates = pd.DataFrame({"x": [0, 1, 2, 3]})
        fitted = fit_surrogate(study, candidates)

        scores = acquisition_values(fitted, encode_frame(candidates, study), "logei", 2.0)

        self.assertEqual(scores.shape, (4,))
    def test_campaign_seed_isolates_local_bo_from_process_rng_state(self) -> None:
        categories = list(range(6))
        candidates = pd.DataFrame({"x": categories})
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=6, features=["x"], categories={"x": categories},
            initial=[{"x": x, "yield": value} for x, value in zip(categories[:4], [0, 1, 4, 9], strict=True)],
        )

        def evaluate(process_seed: int) -> tuple[dict[str, object], np.ndarray, np.ndarray, np.ndarray]:
            random.seed(process_seed)
            np.random.seed(process_seed)
            torch.manual_seed(process_seed)
            fitted = fit_surrogate(study, candidates)
            x = encode_frame(candidates, study)
            mean, variance = posterior_rows(fitted, x, study.direction)
            scores = acquisition_values(fitted, x, "noisy_logei", 2.0)
            return diagnostics(fitted, study), mean, variance, scores

        first = evaluate(1)
        second = evaluate(999)

        self.assertEqual(first[0], second[0])
        for left, right in zip(first[1:], second[1:], strict=True):
            np.testing.assert_array_equal(left, right)

    def test_local_bo_restores_process_rng_state(self) -> None:
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=4, features=["x"], categories={"x": [0, 1, 2, 3]},
            initial=[{"x": 0, "yield": 0}, {"x": 1, "yield": 1}, {"x": 2, "yield": 4}],
        )
        candidates = pd.DataFrame({"x": [0, 1, 2, 3]})
        random.seed(17)
        np.random.seed(17)
        torch.manual_seed(17)
        python_state = random.getstate()
        numpy_state = np.random.get_state()
        torch_state = torch.random.get_rng_state().clone()

        fitted = fit_surrogate(study, candidates)
        acquisition_values(fitted, encode_frame(candidates, study), "noisy_logei", 2.0)

        self.assertEqual(random.getstate(), python_state)
        current_numpy_state = np.random.get_state()
        self.assertEqual(current_numpy_state[0], numpy_state[0])
        np.testing.assert_array_equal(current_numpy_state[1], numpy_state[1])
        self.assertEqual(current_numpy_state[2:], numpy_state[2:])
        self.assertTrue(torch.equal(torch.random.get_rng_state(), torch_state))

    def test_local_seed_changes_with_campaign_seed_observation_state_and_operation(self) -> None:
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=4, features=["x"], categories={"x": [0, 1]}, initial=[{"x": 0, "yield": 0}],
        )

        retry_seed = local_bo_seed(study, "suggest:noisy_logei")
        self.assertEqual(retry_seed, local_bo_seed(study, "suggest:noisy_logei"))
        self.assertNotEqual(retry_seed, local_bo_seed(study, "diagnostics"))
        study.seed = 124
        self.assertNotEqual(retry_seed, local_bo_seed(study, "suggest:noisy_logei"))
        study.seed = 123
        study.initial.append({"x": 1, "yield": 1})
        self.assertNotEqual(retry_seed, local_bo_seed(study, "suggest:noisy_logei"))
        observed = copy.deepcopy(study)
        observed.trials.append(Trial(
            trial_id="trial", candidate_id="candidate", query_index=1, config={"x": 1}, status="observed", metrics={"yield": 1.0},
        ))
        self.assertNotEqual(retry_seed, local_bo_seed(observed, "suggest:noisy_logei"))

    def test_local_seed_ignores_observation_arrival_order(self) -> None:
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=4, features=["x"], categories={"x": [0, 1, 2]},
            trials=[
                Trial(trial_id="one", candidate_id="one", query_index=1, config={"x": 1}, status="observed", metrics={"yield": 1.0}),
                Trial(trial_id="two", candidate_id="two", query_index=2, config={"x": 2}, status="observed", metrics={"yield": 4.0}),
            ],
        )
        reversed_study = copy.deepcopy(study)
        reversed_study.trials.reverse()

        self.assertEqual(local_bo_seed(study, "suggest:noisy_logei"), local_bo_seed(reversed_study, "suggest:noisy_logei"))

    def test_fit_retries_optimization_warning_without_changing_global_rng(self) -> None:
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=4, features=["x"], categories={"x": [0, 1, 2]},
            initial=[{"x": 0, "yield": 0}, {"x": 1, "yield": 1}, {"x": 2, "yield": 4}],
        )
        attempts = 0

        def optimizer(_mll, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                warnings.warn("retry", OptimizationWarning)
            return OptimizationResult(step=attempts, fval=0.0, status=OptimizationStatus.SUCCESS)

        torch.manual_seed(17)
        torch_state = torch.random.get_rng_state().clone()

        original_fit = backend.fit_gpytorch_mll
        with patch.object(backend, "fit_gpytorch_mll", side_effect=lambda mll: original_fit(mll, optimizer=optimizer)):
            fit_surrogate(study, pd.DataFrame({"x": [0, 1, 2]}))

        self.assertEqual(attempts, 2)
        self.assertTrue(torch.equal(torch.random.get_rng_state(), torch_state))

    def test_diagnostics_cross_validation_is_deterministic(self) -> None:
        categories = list(range(6))
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=6, features=["x"], categories={"x": categories},
            initial=[{"x": x, "yield": value} for x, value in zip(categories, [0, 1, 4, 9, 16, 40], strict=True)],
        )
        candidates = pd.DataFrame({"x": categories})

        first = diagnostics(fit_surrogate(study, candidates, operation="diagnostics"), study)
        torch.manual_seed(999)
        second = diagnostics(fit_surrogate(study, candidates, operation="diagnostics"), study)

        self.assertEqual(first, second)

    def test_lengthscale_floor_prevents_categorical_degeneration(self) -> None:
        """floor 参数应钳制 categorical lengthscale, 防止小样本退化到 0."""
        study = Study(
            study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
            seed=123, budget=8, features=["x", "y"], categories={"x": [0, 1, 2, 3], "y": [0, 1, 2, 3]},
            initial=[
                {"x": x, "y": y, "yield": 10 * x + y}
                for x in range(4) for y in range(2)
            ],
        )
        candidates = pd.DataFrame({"x": [0, 1, 2, 3], "y": [0, 1, 2, 3]})

        floored = diagnostics(fit_surrogate(study, candidates, operation="floor-test", lengthscale_floor=1e-2), study)
        for feature, lengthscale in floored["lengthscales"].items():
            self.assertGreaterEqual(lengthscale, 1e-2, f"{feature} lengthscale below floor")

    def test_lengthscale_floor_opt_in_does_not_change_default(self) -> None:
        """默认(无 floor)保持旧行为——退化维度仍可为 0; 显式 floor 才钳制."""
        def build() -> Study:
            return Study(
                study_id="study", campaign_id="campaign", public_root=".", target="yield", direction="maximize",
                seed=0, budget=8, features=["x", "y"], categories={"x": [0, 1, 2, 3], "y": [0, 1, 2, 3]},
                initial=[{"x": x, "y": y, "yield": float(10 * x)} for x in range(4) for y in range(2)],
            )
        candidates = pd.DataFrame({"x": [0, 1, 2, 3], "y": [0, 1, 2, 3]})

        # 默认路径: 不抛错, 行为与之前一致——允许某个维度退化到极小/极大(无约束)
        default = diagnostics(fit_surrogate(build(), candidates, operation="default-test"), build())
        self.assertGreaterEqual(default["lengthscales"]["y"], 0.0)

        # 显式 floor: 每个维度都被钳制到下界
        floored = diagnostics(fit_surrogate(build(), candidates, operation="floor-test", lengthscale_floor=1e-2), build())
        for feature, lengthscale in floored["lengthscales"].items():
            self.assertGreaterEqual(lengthscale, 1e-2, f"{feature} below floor")

    def test_diverse_candidate_positions_pure_rank(self) -> None:
        scores = np.array([0.1, 0.5, 0.2, 0.9, 0.3])
        x = torch.tensor([[0], [1], [2], [3], [4]], dtype=torch.double)
        pure = backend.diverse_candidate_positions(scores, x, q=3, pure_rank=True)
        ranked = backend.ranked_candidate_positions(scores, q=3)
        np.testing.assert_array_equal(pure, ranked)

    def test_diverse_candidate_positions_normalized_weights(self) -> None:
        # Candidate 0: score=0.04 (high), x=0
        # Candidate 1: score=0.039 (very high, near candidate 0), x=0.1
        # Candidate 2: score=0.01 (low), x=10.0 (far away)
        scores = np.array([0.04, 0.039, 0.01])
        x = torch.tensor([[0.0], [0.1], [10.0]], dtype=torch.double)
        
        # With normalized weights (0.8 score + 0.2 dist), Candidate 1 should still be selected before Candidate 2
        # because its normalized score (0.967) strongly outweighs candidate 2's normalized distance advantage
        chosen = backend.diverse_candidate_positions(scores, x, q=2, pure_rank=False)
        self.assertEqual(list(chosen), [0, 1])


if __name__ == "__main__":
    unittest.main()


class SensitivityDiagnosticsTest(unittest.TestCase):
    """sensitivity: per-dimension first-order sensitivity proxy for categorical GP."""

    def _study(self, features, categories, configs, values):
        return Study(
            study_id="s", campaign_id="c", public_root=".", target="y", direction="maximize",
            seed=0, budget=len(configs), features=features, categories=categories,
            trials=[Trial(trial_id=f"t{i}", candidate_id=f"c{i}", query_index=i,
                          config=configs[i], status="observed", source="campaign",
                          metrics={"y": values[i]}) for i in range(len(configs))],
        )

    def test_diagnostics_reports_sensitivity_per_feature(self):
        features = ["cat1", "num"]
        categories = {"cat1": ["a", "b", "c"], "num": [0.0, 1.0, 2.0]}
        configs = [{"cat1": ["a", "b", "c"][i % 3], "num": [0.0, 1.0, 2.0][i % 3]} for i in range(9)]
        values = [float(i % 3) for i in range(9)]
        study = self._study(features, categories, configs, values)
        candidates = pd.DataFrame([{"cat1": c, "num": n} for c in categories["cat1"] for n in categories["num"]])

        result = diagnostics(fit_surrogate(study, candidates), study)

        self.assertIn("sensitivity", result)
        self.assertEqual(set(result["sensitivity"].keys()), set(features))
        for value in result["sensitivity"].values():
            self.assertTrue(np.isfinite(value))

    def test_sensitivity_ranks_highly_varying_dimension_above_flat_one(self):
        # cat1 drives y strongly; num2 is genuinely flat (y independent of it).
        # Full grid so the two dimensions are structurally separable (not identical
        # cyclic codes).
        import itertools

        features = ["cat1", "num2"]
        categories = {"cat1": ["a", "b", "c"], "num2": [0.0, 1.0, 2.0]}
        configs, values = [], []
        for c1, num2 in itertools.product(categories["cat1"], categories["num2"]):
            configs.append({"cat1": c1, "num2": num2})
            values.append(2.0 if c1 == "c" else 0.0)
        study = self._study(features, categories, configs, values)
        candidates = pd.DataFrame([{"cat1": c, "num2": n} for c in categories["cat1"] for n in categories["num2"]])

        result = diagnostics(fit_surrogate(study, candidates), study)

        self.assertGreater(result["sensitivity"]["cat1"], result["sensitivity"]["num2"])

    def test_sensitivity_is_deterministic(self):
        features = ["cat1"]
        categories = {"cat1": ["a", "b", "c"]}
        configs = [{"cat1": ["a", "b", "c"][i % 3]} for i in range(6)]
        values = [float(i % 3) for i in range(6)]
        candidates = pd.DataFrame([{"cat1": c} for c in categories["cat1"]])

        def run():
            return diagnostics(fit_surrogate(self._study(features, categories, configs, values), candidates), study_cfg)[
                "sensitivity"
            ]

        import copy
        study_cfg = self._study(features, categories, configs, values)
        first = run()
        second = run()
        self.assertEqual(first, second)
