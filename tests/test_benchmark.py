from pathlib import Path
import tempfile
import unittest

from patchtrial.benchmark import load_tasks, prepare


class BenchmarkTests(unittest.TestCase):
    def test_manifest_has_required_matrix_coverage(self):
        tasks = load_tasks()
        self.assertGreaterEqual(len(tasks), 10)
        self.assertEqual({task["language"] for task in tasks}, {"python", "javascript"})
        self.assertGreaterEqual(len({task["fault_family"] for task in tasks}), 4)

    def test_prepare_creates_clean_git_repository(self):
        task = load_tasks()[0]
        with tempfile.TemporaryDirectory() as temp:
            root = prepare(task, Path(temp) / "fixture")
            self.assertTrue((root / ".git").is_dir())
            self.assertTrue((root / "pricing.py").is_file())


if __name__ == "__main__":
    unittest.main()
