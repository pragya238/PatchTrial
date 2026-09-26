from pathlib import Path
import json
import tempfile
import unittest

from patchtrial.scorecard import aggregate


class ScorecardTests(unittest.TestCase):
    def test_aggregates_proof_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for index, report in enumerate([
                {"verdict": "ACCEPTED", "valid_trials": 3, "killed_trials": 3, "strengthening_applied": True, "prompt_tokens": 10, "completion_tokens": 5},
                {"verdict": "NEEDS_STRONGER_TESTS", "valid_trials": 2, "killed_trials": 1, "strengthening_applied": False, "prompt_tokens": 20, "completion_tokens": 5},
            ]):
                path = Path(temp) / f"proof-{index}.json"
                path.write_text(json.dumps(report))
                paths.append(path)
            result = aggregate(paths)
        self.assertEqual(result["runs"], 2)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["valid_counterfeits"], 5)
        self.assertEqual(result["counterfeits_killed"], 4)
        self.assertEqual(result["counterfeit_kill_rate"], 80)
        self.assertEqual(result["prompt_tokens"], 30)


if __name__ == "__main__":
    unittest.main()
