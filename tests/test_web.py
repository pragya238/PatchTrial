import unittest
from pathlib import Path

from patchtrial.web import JobStore


class WebTests(unittest.TestCase):
    def test_runtime_model_configuration_is_memory_only(self):
        store = JobStore()
        config = store.configure({
            "api_key": "secret",
            "base_url": "https://api.deepseek.com/",
            "model": "deepseek-flash",
            "provider": "deepseek",
        })
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(store.config().api_key, "secret")

    def test_runtime_configuration_requires_https(self):
        store = JobStore()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            store.configure({"api_key": "x", "base_url": "http://remote.test", "model": "m"})

    def test_runtime_configuration_supports_free_tier_gateways(self):
        cases = [
            ("openrouter", "https://openrouter.ai/api/v1", "openrouter/free", "sk-or-test"),
            ("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "secret"),
            (
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "gemini-3.8-flash",
                "secret",
            ),
        ]
        for provider, base_url, model, api_key in cases:
            with self.subTest(provider=provider):
                config = JobStore().configure({
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "provider": provider,
                })
                self.assertEqual(config.provider, provider)

    def test_openrouter_rejects_a_key_from_another_provider(self):
        with self.assertRaisesRegex(ValueError, "OpenRouter keys begin"):
            JobStore().configure({
                "api_key": "AIza-gemini-key",
                "base_url": "https://openrouter.ai/api/v1",
                "model": "openrouter/free",
                "provider": "openrouter",
            })

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            JobStore().configure({
                "api_key": "secret",
                "base_url": "https://example.test/v1",
                "model": "model",
                "provider": "mystery",
            })

    def test_provider_change_requires_explicit_activation(self):
        page = (Path(__file__).parent.parent / "dashboard" / "dist" / "live.html").read_text()
        self.assertIn("Click “Use for this session” to activate", page)
        self.assertIn("run.disabled=true", page)

    def test_public_workspace_has_a_safe_runnable_demo(self):
        page = (Path(__file__).parent.parent / "dashboard" / "dist" / "live.html").read_text()
        self.assertIn("Browser demo ready · no API key needed", page)
        self.assertIn("function runPublicTrial()", page)
        self.assertIn("if(!isLocal){runPublicTrial();return}", page)
        self.assertIn("$('#config').hidden=true", page)

    def test_job_requires_repository_and_task(self):
        store = JobStore()
        with self.assertRaisesRegex(ValueError, "Repository path and task"):
            store.create({"repo": "", "task": ""})

    def test_missing_task_is_rejected_before_thread_starts(self):
        store = JobStore()
        with self.assertRaises(ValueError):
            store.create({"repo": "/tmp/example"})


if __name__ == "__main__":
    unittest.main()
