import os
from pathlib import Path
import unittest
from unittest.mock import patch

from patchtrial.cli import build_parser
from patchtrial.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_candidate_only_baseline_flag(self):
        with patch.dict("os.environ", {"PATCHTRIAL_STOP_AFTER_CANDIDATE": "true"}, clear=False):
            config = Config.from_env(require_key=False)
        self.assertTrue(config.stop_after_candidate)

    def test_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigError):
                Config.from_env()

    def test_reads_model_adapter_values(self):
        values = {
            "AI_API_KEY": "secret",
            "AI_BASE_URL": "https://gateway.example/v1/",
            "AI_MODEL": "qwen-model",
            "AI_PROVIDER": "qwen",
        }
        with patch.dict(os.environ, values, clear=True):
            config = Config.from_env()
        self.assertEqual(config.base_url, "https://gateway.example/v1")
        self.assertEqual(config.model, "qwen-model")
        self.assertEqual(config.provider, "qwen")

    def test_cli_reads_evaluation_environment(self):
        values = {
            "TARGET_REPO": "/tmp/example-target",
            "TEST_COMMAND": "make verify",
        }
        with patch.dict(os.environ, values, clear=True):
            args = build_parser().parse_args(["--task", "fix it"])
        self.assertEqual(args.repo, "/tmp/example-target")
        self.assertEqual(args.test_command, "make verify")

    def test_qwen_provider_has_a_code_model_preset(self):
        with patch.dict(os.environ, {"AI_API_KEY": "secret", "AI_PROVIDER": "qwen"}, clear=True):
            config = Config.from_env()
        self.assertEqual(config.provider, "qwen")
        self.assertEqual(config.model, "qwen3-coder-plus")
        self.assertIn("dashscope-intl", config.base_url)


if __name__ == "__main__":
    unittest.main()
