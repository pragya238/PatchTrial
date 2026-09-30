import json
import unittest
from unittest.mock import patch

from patchtrial.config import Config
from patchtrial.model import ModelClient, _redact_secret, is_openrouter_free_text_model


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
    def test_secret_redaction(self):
        self.assertEqual(
            _redact_secret("provider echoed sk-sensitive-value", "sk-sensitive-value"),
            "provider echoed [REDACTED]",
        )

    def test_openrouter_excludes_non_text_and_safety_models(self):
        base = {
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        }
        self.assertTrue(is_openrouter_free_text_model({**base, "id": "cohere/north-mini-code:free"}))
        self.assertFalse(is_openrouter_free_text_model({
            **base,
            "id": "google/lyria-3-pro-preview",
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text", "audio"],
            },
        }))
        self.assertFalse(is_openrouter_free_text_model({
            **base,
            "id": "vendor/content-safety:free",
        }))
        self.assertFalse(is_openrouter_free_text_model({**base, "id": "openrouter/free"}))

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

    def test_qwen_model_discovery_uses_native_catalog_endpoint(self):
        captured = {}
        catalog_payload = {
            "output": {
                "models": [
                    {
                        "model": "qwen3-coder-plus",
                        "name": "Qwen Coder",
                        "features": ["structured-outputs"],
                    }
                ]
            }
        }

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            return FakeHTTPResponse(catalog_payload)

        config = Config(
            api_key="qwen-key",
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            model="qwen3-coder-plus",
            provider="qwen",
        )
        with patch("patchtrial.model.request.urlopen", side_effect=fake_urlopen):
            models = ModelClient(config).list_models()

        self.assertIn("/api/v1/models?", captured["url"])
        self.assertIn("providers=qwen", captured["url"])
        self.assertEqual(captured["authorization"], "Bearer qwen-key")
        self.assertEqual(models[0]["id"], "qwen3-coder-plus")
        self.assertEqual(models[0]["supported_parameters"], ["response_format"])

    def test_openrouter_requires_json_capable_route(self):
        captured = {}
        catalog_payload = {
            "data": [
                {
                    "id": "example/json-free:free",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 100_000,
                    "architecture": {"output_modalities": ["text"]},
                    "supported_parameters": ["response_format"],
                },
                {
                    "id": "example/second-free:free",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 80_000,
                    "architecture": {"output_modalities": ["text"]},
                    "supported_parameters": ["response_format"],
                },
            ]
        }
        response_payload = {
            "choices": [{"message": {"content": '{"name":"finish","arguments":{}}'}}],
        }

        def fake_urlopen(req, timeout):
            if req.get_method() == "GET":
                return FakeHTTPResponse(catalog_payload)
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
        self.assertEqual(captured["payload"]["model"], "example/json-free:free")
        self.assertEqual(captured["payload"]["models"], ["example/second-free:free"])

    def test_openrouter_does_not_require_json_when_a_fallback_lacks_support(self):
        captured = {}
        catalog_payload = {
            "data": [
                {
                    "id": "example/plain-free:free",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 100_000,
                    "architecture": {"output_modalities": ["text"]},
                    "supported_parameters": ["temperature"],
                }
            ]
        }
        response_payload = {
            "choices": [{"message": {"content": '{"name":"finish","arguments":{}}'}}],
        }

        def fake_urlopen(req, timeout):
            if req.get_method() == "GET":
                return FakeHTTPResponse(catalog_payload)
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

        self.assertEqual(captured["payload"]["model"], "example/plain-free:free")
        self.assertNotIn("response_format", captured["payload"])

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
