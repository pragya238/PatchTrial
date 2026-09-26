from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from patchtrial.config import Config
from patchtrial.engine import PatchTrialEngine
from patchtrial.model import ModelResponse
from patchtrial.repository import Repository


CANDIDATE_PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

COUNTERFEIT_PATCH = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return abs(a) + abs(b)
"""

STRENGTHENING_PATCH = """diff --git a/test_calculator.py b/test_calculator.py
--- a/test_calculator.py
+++ b/test_calculator.py
@@ -5,2 +5,5 @@ class Tests(unittest.TestCase):
     def test_positive(self):
         self.assertEqual(add(2, 3), 5)
+
+    def test_mixed_signs(self):
+        self.assertEqual(add(-2, 1), -1)
"""


class FakeModel:
    def __init__(self):
        self.responses = [
            json.dumps({
                "reason": "Apply the minimal arithmetic fix",
                "action": {"name": "apply_patch", "arguments": {"patch": CANDIDATE_PATCH}},
            }),
            json.dumps({
                "reason": "Candidate is ready for harness verification",
                "action": {"name": "finish", "arguments": {"summary": "fix add"}},
            }),
            json.dumps({
                "counterfeits": [{
                    "name": "absolute_values",
                    "hypothesis": "negative operands are handled incorrectly",
                    "patch": COUNTERFEIT_PATCH,
                }]
            }),
        ]

    def complete(self, messages):
        return ModelResponse(self.responses.pop(0), prompt_tokens=10, completion_tokens=5)


class StrengtheningModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.responses.append(json.dumps({
            "patch": STRENGTHENING_PATCH,
            "rationale": "mixed signs distinguish addition from absolute-value addition",
        }))


class ReplaceTextModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.responses[0] = json.dumps({
            "reason": "Use an exact edit instead of a fragile diff",
            "action": {
                "name": "replace_text",
                "arguments": {
                    "path": "calculator.py",
                    "old": "return a - b",
                    "new": "return a + b",
                },
            },
        })


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


class EngineIntegrationTests(unittest.TestCase):
    def test_exact_text_edit_can_build_candidate_without_diff_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
            (root / "test_calculator.py").write_text(
                "import unittest\nfrom calculator import add\n\n"
                "class Tests(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(-2, 1), -1)\n"
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", "initial")
            engine = PatchTrialEngine(
                Config(api_key="fake", base_url="https://invalid", model="fake"),
                Repository(root),
                ReplaceTextModel(),
                test_command="python -m unittest discover -v",
                event=lambda _: None,
            )
            report_path = Path(temp).parent / f"{root.name}-replace-proof.json"
            try:
                result = engine.run("Correct add", report_path)
                self.assertEqual(result.report.verdict, "ACCEPTED")
                self.assertIn("return a + b", (root / "calculator.py").read_text())
            finally:
                report_path.unlink(missing_ok=True)

    def test_reproduction_requires_real_failure_before_production_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", "initial")
            engine = PatchTrialEngine(
                Config(api_key="fake", base_url="https://invalid", model="fake"),
                Repository(root),
                FakeModel(),
                test_command="python -m unittest",
                event=lambda _: None,
            )
            before_failure = engine._execute(
                "record_reproduction", {"command": "python -c fail", "evidence": "x"}
            )
            self.assertIn("TOOL ERROR", before_failure)
            engine._execute(
                "run_command", {"command": "python -c 'raise SystemExit(1)'"}
            )
            accepted = engine._execute(
                "record_reproduction", {"command": "python", "evidence": "baseline fails"}
            )
            self.assertIn("recorded", accepted)
            self.assertTrue(engine.reproduction_recorded)

    def test_reproduction_rejects_failure_after_production_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", "initial")
            engine = PatchTrialEngine(
                Config(api_key="fake", base_url="https://invalid", model="fake"),
                Repository(root),
                FakeModel(),
                test_command="python -m unittest",
                event=lambda _: None,
            )
            engine._execute("apply_patch", {"patch": CANDIDATE_PATCH})
            engine._execute(
                "run_command", {"command": "python -c 'raise SystemExit(1)'"}
            )
            rejected = engine._execute(
                "record_reproduction", {"command": "python", "evidence": "late failure"}
            )
            self.assertIn("production-code changes", rejected)
            self.assertFalse(engine.reproduction_recorded)

    def test_context_history_is_bounded_without_losing_task(self):
        config = Config(
            api_key="fake",
            base_url="https://invalid",
            model="fake",
            max_context_chars=1_000,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            engine = PatchTrialEngine(
                config,
                Repository(root),
                FakeModel(),
                test_command="python -m unittest",
                event=lambda _: None,
            )
            messages = [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "important task"},
                {"role": "assistant", "content": "old" * 500},
                {"role": "user", "content": "recent evidence"},
            ]
            bounded = engine._bounded_messages(messages)
        self.assertEqual(bounded[0]["content"], "system")
        self.assertEqual(bounded[1]["content"], "important task")
        self.assertEqual(bounded[-1]["content"], "recent evidence")
        self.assertTrue(any("compacted" in item["content"] for item in bounded))

    def test_counterfeit_is_killed_and_candidate_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            (root / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class Tests(unittest.TestCase):\n"
                "    def test_positive(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n\n"
                "    def test_negative(self):\n"
                "        self.assertEqual(add(-2, 1), -1)\n",
                encoding="utf-8",
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", "initial")

            config = Config(api_key="fake", base_url="https://invalid", model="fake")
            repository = Repository(root)
            engine = PatchTrialEngine(
                config,
                repository,
                FakeModel(),
                test_command="python -m unittest discover -v",
                event=lambda _: None,
            )
            report_path = Path(temp).parent / f"{root.name}-proof.json"
            try:
                result = engine.run("Correct the add function", report_path)
                self.assertEqual(result.report.verdict, "ACCEPTED")
                self.assertEqual(result.report.killed_trials, 1)
                self.assertEqual(
                    (root / "calculator.py").read_text(),
                    "def add(a, b):\n    return a + b\n",
                )
            finally:
                report_path.unlink(missing_ok=True)

    def test_surviving_counterfeit_triggers_stronger_test(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "calculator.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            (root / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class Tests(unittest.TestCase):\n"
                "    def test_positive(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            git(root, "add", ".")
            git(root, "commit", "-qm", "initial")

            config = Config(api_key="fake", base_url="https://invalid", model="fake")
            engine = PatchTrialEngine(
                config,
                Repository(root),
                StrengtheningModel(),
                test_command="python -m unittest discover -v",
                event=lambda _: None,
            )
            report_path = Path(temp).parent / f"{root.name}-proof.json"
            try:
                result = engine.run("Correct the add function", report_path)
                self.assertEqual(result.report.verdict, "ACCEPTED")
                self.assertEqual(result.report.killed_trials, 1)
                self.assertIn("test_mixed_signs", (root / "test_calculator.py").read_text())
                self.assertIn("test_mixed_signs", result.candidate_diff)
                self.assertEqual(
                    (root / "calculator.py").read_text(),
                    "def add(a, b):\n    return a + b\n",
                )
            finally:
                report_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
