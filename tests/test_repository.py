from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from patchtrial.repository import Repository, RepositoryError


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        git(self.root, "add", "app.py")
        git(self.root, "commit", "-qm", "initial")
        self.repo = Repository(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_blocks_path_escape(self):
        with self.assertRaises(RepositoryError):
            self.repo.read_file("../outside.txt")

    def test_applies_and_reverses_patch(self):
        patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
        self.assertTrue(self.repo.apply_patch(patch).ok)
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 2\n")
        self.assertTrue(self.repo.apply_patch(patch, reverse=True).ok)
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 1\n")

    def test_recounts_incorrect_hunk_lengths_and_strips_fences(self):
        malformed_counts = """Here is the patch:
```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,99 +1,99 @@
-VALUE = 1
+VALUE = 2
```
"""
        self.assertTrue(self.repo.apply_patch(malformed_counts).ok)
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 2\n")

    def test_replace_text_requires_one_exact_match(self):
        result = self.repo.replace_text("app.py", "VALUE = 1", "VALUE = 2")
        self.assertIn("Replaced one", result)
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 2\n")
        with self.assertRaisesRegex(RepositoryError, "found 0 matches"):
            self.repo.replace_text("app.py", "VALUE = 1", "VALUE = 3")

    def test_create_file_rejects_overwrite(self):
        self.repo.create_file("tests/test_app.py", "assert True\n")
        self.assertEqual((self.root / "tests/test_app.py").read_text(), "assert True\n")
        with self.assertRaisesRegex(RepositoryError, "already exists"):
            self.repo.create_file("tests/test_app.py", "assert False\n")

    def test_restore_clean_reverts_tracked_and_untracked_changes(self):
        self.repo.replace_text("app.py", "VALUE = 1", "VALUE = 2")
        self.repo.create_file("new.py", "NEW = True\n")
        self.assertTrue(self.repo.status())
        self.repo.restore_clean()
        self.assertEqual(self.repo.status(), "")
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 1\n")
        self.assertFalse((self.root / "new.py").exists())

    def test_diff_includes_untracked_files(self):
        (self.root / "new_test.py").write_text("assert True\n", encoding="utf-8")
        diff = self.repo.diff()
        self.assertIn("new_test.py", diff)
        self.assertIn("assert True", diff)

    def test_diff_excludes_generated_cache_files(self):
        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "app.pyc").write_bytes(b"generated")
        self.assertNotIn("app.pyc", self.repo.diff())

    def test_command_allowlist_rejects_unknown_executable(self):
        with self.assertRaises(RepositoryError):
            self.repo.run_command("curl https://example.com")

    def test_model_api_key_is_not_exposed_to_repository_commands(self):
        previous = os.environ.get("AI_API_KEY")
        os.environ["AI_API_KEY"] = "must-not-leak"
        try:
            result = self.repo.run_command(
                "python -c 'import os; print(os.getenv(\"AI_API_KEY\", \"missing\"))'"
            )
        finally:
            if previous is None:
                os.environ.pop("AI_API_KEY", None)
            else:
                os.environ["AI_API_KEY"] = previous
        self.assertEqual(result.stdout.strip(), "missing")

    def test_search_and_read(self):
        self.assertIn("app.py:1:VALUE", self.repo.search_code("VALUE"))
        self.assertIn("VALUE = 1", self.repo.read_file("app.py"))

    def test_detects_pytest_from_pyproject(self):
        (self.root / "pyproject.toml").write_text(
            '[project]\ndependencies = ["pytest"]\n', encoding="utf-8"
        )
        (self.root / "tests").mkdir()
        self.assertEqual(self.repo.detect_test_command(), "python -m pytest -q")

    def test_uses_declared_javascript_test_script_without_jest_flags(self):
        (self.root / "package.json").write_text(
            '{"scripts":{"test":"vitest run"}}\n', encoding="utf-8"
        )
        self.assertEqual(self.repo.detect_test_command(), "npm test")


if __name__ == "__main__":
    unittest.main()
