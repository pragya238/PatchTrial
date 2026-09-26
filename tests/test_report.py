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

    def test_confidence_penalizes_too_little_or_repetitive_evidence(self):
        report = ProofReport(
            task="x", model="m", test_command="make test",
            min_valid_counterfeits=3, min_fault_categories=2,
        )
        report.trials = [TrialResult("a", "fault", True, True, 1, category="boundary")]
        self.assertEqual(report.survival_score, 100.0)
        self.assertLess(report.evidence_confidence, 20.0)


if __name__ == "__main__":
    unittest.main()
