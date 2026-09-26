import unittest

from patchtrial.web import JobStore


class WebTests(unittest.TestCase):
    def test_runtime_model_configuration_is_memory_only(self):
        store = JobStore()
        config = store.configure({
            "api_key": "secret",
            "base_url": "https://api.deepseek.com/",
            "model": "deepseek-flash",
        })
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(store.config().api_key, "secret")

    def test_runtime_configuration_requires_https(self):
        store = JobStore()
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            store.configure({"api_key": "x", "base_url": "http://remote.test", "model": "m"})

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
