from pathlib import Path
import json
import tempfile
import unittest

from patchtrial.report import ProofReport, TrialResult


class ReportTests(unittest.TestCase):
    def test_score_counts_only_valid_trials(self):
        report = ProofReport(task="x", model="m", test_command="make test")
        report.trials = [
            TrialResult("a", "fault a", True, True, 1),
            TrialResult("b", "fault b", True, False, 0),
            TrialResult("invalid", "bad diff", False, False, None),
        ]
        self.assertEqual(report.valid_trials, 2)
        self.assertEqual(report.killed_trials, 1)
        self.assertEqual(report.survival_score, 50.0)

    def test_writes_machine_readable_proof(self):
        report = ProofReport(task="x", model="m", test_command="make test", verdict="ACCEPTED")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "proof.json"
            report.write(path)
            payload = json.loads(path.read_text())
        self.assertEqual(payload["verdict"], "ACCEPTED")
        self.assertIn("patch_survival_score", payload)


if __name__ == "__main__":
    unittest.main()
