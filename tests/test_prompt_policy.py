from pathlib import Path
import unittest


class PromptPolicyTest(unittest.TestCase):
    def test_domain_priors_require_exact_identity_and_surrogate_comparison(self) -> None:
        prompt = Path("profiles/paper-reproduction/PAPER_SYSTEM.md").read_text()

        self.assertIn("same `candidate_id`", prompt)
        self.assertIn("use `lenz_predict` or `lenz_score`", prompt)
        self.assertIn("finish with `commit_candidate`", prompt)
        self.assertIn("manually grouped non-identical Candidates", prompt)

        lenz_ref = Path("profiles/paper-reproduction/PAPER_LENZ_REF.md").read_text()
        self.assertIn("negative value means EI < 1, not negative improvement, zero improvement, or convergence", prompt)
        self.assertIn("scale and stability of acquisition values across global Candidates", prompt)
        self.assertIn("matched comparison or repeated experiment", prompt)
        self.assertIn("After consecutive local moves along the same dimension", prompt)
        self.assertIn("exactly one evaluation remains", prompt)
        self.assertIn("near_best_suggestions", prompt)
        self.assertIn("within `1e-5`", prompt)
        self.assertIn("`preferred_suggestion`", prompt)
        self.assertIn("commit it by default", prompt)
        self.assertIn("acquisition ties are not override evidence", prompt)
        self.assertIn("`ucb` with `beta=16`", prompt)
        self.assertIn("default low-trust exploration policy", prompt)
        self.assertIn("`train_r2`: in-sample", lenz_ref)
        self.assertIn("`cv_r2`: strict K-fold out-of-sample", lenz_ref)


if __name__ == "__main__":
    unittest.main()
