import unittest

import pandas as pd
import torch

from boagent.backend import acquisition_values, diagnostics, encode_frame, fit_surrogate, ranked_candidate_positions
from boagent.state import Study


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


if __name__ == "__main__":
    unittest.main()
