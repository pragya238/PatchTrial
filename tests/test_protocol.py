import unittest

from patchtrial.protocol import ProtocolError, parse_action, parse_json_object


class ProtocolTests(unittest.TestCase):
    def test_extracts_json_from_markdown_fence(self):
        value = parse_json_object('```json\n{"action":{"name":"finish","arguments":{}}}\n```')
        self.assertEqual(value["action"]["name"], "finish")

    def test_rejects_unknown_tool(self):
        with self.assertRaises(ProtocolError):
            parse_action('{"action":{"name":"delete_everything","arguments":{}}}', {"finish"})

    def test_accepts_flat_action_shape(self):
        action = parse_action('{"name":"finish","arguments":{}}', {"finish"})
        self.assertEqual(action.name, "finish")

    def test_rejects_non_object(self):
        with self.assertRaises(ProtocolError):
            parse_json_object('[1, 2, 3]')


if __name__ == "__main__":
    unittest.main()

