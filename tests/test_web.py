import unittest

from patchtrial.web import JobStore


class WebTests(unittest.TestCase):
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
