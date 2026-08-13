import random
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch

from benchmark import run_gp


class RunGpSeedTest(unittest.TestCase):
    def test_declared_seed_controls_python_numpy_and_torch_rngs(self) -> None:
        states = []

        def capture_rngs(*_args):
            states.append((random.random(), np.random.random(), torch.rand(1).item()))
            raise RuntimeError("captured")

        train = pd.DataFrame({"x": ["a"], "Yield": [1.0]})
        candidates = pd.DataFrame({"x": ["b"]})
        private = pd.DataFrame({"x": ["b"], "Yield": [2.0]})
        with TemporaryDirectory() as directory, patch.object(run_gp.pd, "read_csv", side_effect=[train, candidates, private] * 3), patch.object(run_gp, "fit_surrogate", side_effect=capture_rngs):
            for index, seed in enumerate((123, 123, 456)):
                argv = ["run_gp.py", "--dataset-root", directory, "--output", str(Path(directory) / f"run-{index}"), "--seed", str(seed), "--budget", "1"]
                with patch.object(sys, "argv", argv), self.assertRaisesRegex(RuntimeError, "captured"):
                    run_gp.main()

        self.assertEqual(states[0], states[1])
        self.assertNotEqual(states[0], states[2])


if __name__ == "__main__":
    unittest.main()
