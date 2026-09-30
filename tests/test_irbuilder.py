import unittest

from conversation.irbuilder import IRBuilder, Provider
from conversation.models import ConversationModel, Message


class FromGenericTest(unittest.TestCase):
    def test_builds_model_from_role_content(self):
        raw = {
            "chat_id": "c1",
            "title": "T",
            "source_url": "https://x",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world", "timestamp": 123},
            ],
        }
        model = IRBuilder._from_generic("gemini", raw, "dom")
        self.assertIsInstance(model, ConversationModel)
        self.assertEqual(model.source, "gemini")
        self.assertEqual(model.stable_id, "c1")
        self.assertEqual([m.role for m in model.messages], ["user", "assistant"])
        self.assertEqual(model.messages[1].timestamp, 123)
        self.assertIsNone(model.tree)


class ParseMessageFromApiTest(unittest.TestCase):
    def test_plain_text_and_image_attachment(self):
        msg = {
            "id": "m1",
            "author": {"role": "user"},
            "create_time": 1000.0,
            "content": {
                "content_type": "multimodal",
                "parts": [
                    "draw a cat",
                    {"content_type": "image/png", "asset_pointer": "file-abc", "size_bytes": 10},
                ],
            },
        }
        m = IRBuilder._parse_message_from_api(msg)
        self.assertEqual(m.role, "user")
        self.assertEqual(m.content, "draw a cat")
        self.assertEqual(len(m.attachments), 1)
        self.assertEqual(m.attachments[0].type, "image")
        self.assertEqual(m.attachments[0].mime, "image/png")

    def test_generated_image_prompt(self):
        msg = {
            "id": "m2",
            "author": {"role": "assistant"},
            "content": {"content_type": "text", "parts": [{"prompt": "a sunset", "size": "1024x1024"}]},
        }
        m = IRBuilder._parse_message_from_api(msg)
        self.assertEqual(len(m.attachments), 1)
        att = m.attachments[0]
        self.assertEqual(att.type, "generated_image")
        self.assertEqual(att["meta"]["prompt"], "a sunset")


class FromChatGptApiTest(unittest.TestCase):
    def _raw(self, current_node="b"):
        return {
            "conversation_id": "conv-1",
            "title": "My chat",
            "current_node": current_node,
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None, "children": ["a"]},
                "a": {
                    "id": "a",
                    "parent": "root",
                    "children": ["b"],
                    "message": {"id": "a", "author": {"role": "user"}, "create_time": 1000,
                                "content": {"content_type": "text", "parts": ["question"]}},
                },
                "b": {
                    "id": "b",
                    "parent": "a",
                    "children": [],
                    "message": {"id": "b", "author": {"role": "assistant"}, "create_time": 2000,
                                "content": {"content_type": "text", "parts": ["answer"]}},
                },
            },
        }

    def test_builds_tree_and_active_branch(self):
        model = IRBuilder._from_chatgpt_api(self._raw(), "https://chatgpt.com/c/conv-1")
        self.assertEqual(model.source, "chatgpt")
        self.assertEqual(model.stable_id, "conv-1")
        self.assertIsNotNone(model.tree)
        self.assertEqual([m.content for m in model.messages], ["question", "answer"])
        self.assertEqual([m.role for m in model.messages], ["user", "assistant"])

    def test_attachment_in_tree_message(self):
        raw = self._raw()
        raw["mapping"]["a"]["message"]["content"]["parts"] = [
            "with image",
            {"content_type": "image/png", "asset_pointer": "file-x"},
        ]
        model = IRBuilder._from_chatgpt_api(raw, "https://x")
        user_msg = model.messages[0]
        self.assertEqual(user_msg.content, "with image")
        self.assertEqual(user_msg.attachments[0].type, "image")

    def test_build_dispatch(self):
        model = IRBuilder.build(Provider.GEMINI, {
            "chat_id": "c", "title": "T", "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(model.source, "gemini")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            IRBuilder.build("bogus", {"messages": []})


if __name__ == "__main__":
    unittest.main()
