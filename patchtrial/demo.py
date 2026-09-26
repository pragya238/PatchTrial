"""Deterministic, no-key demonstration of PatchTrial's complete evidence loop."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from .config import Config
from .engine import PatchTrialEngine
from .model import ModelResponse
from .repository import Repository


CANDIDATE = """diff --git a/pricing.py b/pricing.py
--- a/pricing.py
+++ b/pricing.py
@@ -1,2 +1,2 @@
 def discounted(price, percent):
-    return price
+    return price * (1 - percent / 100)
"""

COUNTERFEIT = """diff --git a/pricing.py b/pricing.py
--- a/pricing.py
+++ b/pricing.py
@@ -1,2 +1,2 @@
 def discounted(price, percent):
-    return price * (1 - percent / 100)
+    return abs(price) * (1 - percent / 100)
"""

STRONGER_TEST = """diff --git a/test_pricing.py b/test_pricing.py
--- a/test_pricing.py
+++ b/test_pricing.py
@@ -5,2 +5,5 @@ class PricingTests(unittest.TestCase):
     def test_standard_discount(self):
         self.assertEqual(discounted(100, 20), 80)
+
+    def test_negative_credit_is_preserved(self):
+        self.assertEqual(discounted(-100, 20), -80)
"""


class DemoModel:
    def __init__(self) -> None:
        self.responses = [
            {"reason": "Implement percentage discount", "action": {"name": "apply_patch", "arguments": {"patch": CANDIDATE}}},
            {"reason": "Candidate ready", "action": {"name": "finish", "arguments": {}}},
            {"counterfeits": [{"name": "absolute_credit", "hypothesis": "negative credits lose their sign", "patch": COUNTERFEIT}]},
            {"patch": STRONGER_TEST, "rationale": "negative input distinguishes the counterfeit"},
        ]

    def complete(self, messages: list[dict[str, str]]) -> ModelResponse:
        return ModelResponse(json.dumps(self.responses.pop(0)), 10, 5)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="patchtrial-demo-") as temp:
        root = Path(temp)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "demo@patchtrial.local")
        _git(root, "config", "user.name", "PatchTrial Demo")
        (root / "pricing.py").write_text("def discounted(price, percent):\n    return price\n")
        (root / "test_pricing.py").write_text(
            "import unittest\nfrom pricing import discounted\n\n"
            "class PricingTests(unittest.TestCase):\n"
            "    def test_standard_discount(self):\n"
            "        self.assertEqual(discounted(100, 20), 80)\n"
        )
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "broken pricing baseline")
        report_path = root.parent / "patchtrial-demo-proof.json"
        engine = PatchTrialEngine(
            Config(api_key="demo", base_url="https://unused.invalid", model="deterministic-demo"),
            Repository(root),
            DemoModel(),
            test_command="python -m unittest discover -v",
        )
        result = engine.run("Apply percentage discounts without corrupting credits", report_path)
        print(result.report.summary())
        print("Final diff:\n" + result.candidate_diff)
        print("Proof artifact:\n" + report_path.read_text())
        report_path.unlink(missing_ok=True)
        return 0 if result.report.verdict == "ACCEPTED" else 1


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    raise SystemExit(main())
