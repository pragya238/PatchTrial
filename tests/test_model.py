import json
import unittest
from unittest.mock import patch

from patchtrial.config import Config
from patchtrial.model import ModelClient


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class ModelClientTests(unittest.TestCase):
    def test_openai_compatible_transport(self):
        captured = {}
        payload = {
            "choices": [{"message": {"content": "{\"action\":{\"name\":\"finish\",\"arguments\":{}}}"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
        }

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            captured["payload"] = json.loads(req.data)
            captured["timeout"] = timeout
            return FakeHTTPResponse(payload)

        config = Config(
            api_key="test-key",
            base_url="https://gateway.example/v1",
            model="qwen-test",
        )
        with patch("patchtrial.model.request.urlopen", side_effect=fake_urlopen):
            response = ModelClient(config).complete([{"role": "user", "content": "hello"}])
        self.assertIn("finish", response.content)
        self.assertEqual(response.prompt_tokens, 12)
        self.assertEqual(response.completion_tokens, 7)
        self.assertEqual(captured["url"], "https://gateway.example/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["model"], "qwen-test")
        self.assertEqual(captured["payload"]["messages"][0]["content"], "hello")
        self.assertEqual(captured["timeout"], 120)

    def test_openrouter_requires_json_capable_route(self):
        captured = {}
        response_payload = {
            "choices": [{"message": {"content": '{"name":"finish","arguments":{}}'}}],
        }

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data)
            return FakeHTTPResponse(response_payload)

        config = Config(
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            model="openrouter/free",
            provider="openrouter",
        )
        with patch("patchtrial.model.request.urlopen", side_effect=fake_urlopen):
            ModelClient(config).complete([{"role": "user", "content": "hello"}])

        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["payload"]["provider"], {"require_parameters": True})

    def test_generic_gateway_does_not_receive_openrouter_routing_fields(self):
        captured = {}
        response_payload = {
            "choices": [{"message": {"content": '{"name":"finish","arguments":{}}'}}],
        }

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data)
            return FakeHTTPResponse(response_payload)

        config = Config(api_key="key", base_url="https://gateway.test/v1", model="model")
        with patch("patchtrial.model.request.urlopen", side_effect=fake_urlopen):
            ModelClient(config).complete([{"role": "user", "content": "hello"}])

        self.assertNotIn("response_format", captured["payload"])
        self.assertNotIn("provider", captured["payload"])


if __name__ == "__main__":
    unittest.main()
