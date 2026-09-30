import unittest

from conversation.models import (
    AttachmentNode,
    ConversationModel,
    ConversationTree,
    Message,
    TreeNode,
)
from conversation.serializer import dict_to_model, model_to_dict


def _model_with_tree():
    nodes = {
        "r": TreeNode(id="r", message=None, children_ids=["a"]),
        "a": TreeNode(id="a", message=Message(role="user", content="hi", attachments=[AttachmentNode(type="image", mime="image/png")]), parent_id="r", children_ids=[]),
    }
    tree = ConversationTree(nodes=nodes, root_id="r", active_node_id="a")
    return ConversationModel(
        source="chatgpt", stable_id="cid", title="T", source_url="https://x",
        messages=[Message(role="user", content="hi", attachments=[AttachmentNode(type="image", mime="image/png")])],
        tree=tree, metadata={"provider": "chatgpt"},
    )


class SerializerTest(unittest.TestCase):
    def test_roundtrip_flat_model(self):
        model = ConversationModel(
            source="gemini", stable_id="c1", title="T", source_url="u",
            messages=[Message(role="user", content="hi", timestamp=1.5)],
        )
        restored = dict_to_model(model_to_dict(model))
        self.assertEqual(restored.source, "gemini")
        self.assertEqual(restored.stable_id, "c1")
        self.assertEqual(restored.messages[0].content, "hi")
        self.assertEqual(restored.messages[0].timestamp, 1.5)

    def test_roundtrip_attachment(self):
        model = ConversationModel(
            source="chatgpt", stable_id="c", title="T", source_url="u",
            messages=[Message(role="user", content="hi", attachments=[AttachmentNode(type="image", mime="image/png", name="a.png")])],
        )
        restored = dict_to_model(model_to_dict(model))
        att = restored.messages[0].attachments[0]
        self.assertEqual(att.type, "image")
        self.assertEqual(att.mime, "image/png")
        self.assertEqual(att.name, "a.png")

    def test_roundtrip_tree(self):
        model = _model_with_tree()
        restored = dict_to_model(model_to_dict(model))
        self.assertIsNotNone(restored.tree)
        self.assertEqual(restored.tree.root_id, "r")
        self.assertEqual(restored.tree.active_node_id, "a")
        branch = restored.tree.get_active_branch()
        self.assertEqual([m.content for m in branch], ["hi"])
        self.assertEqual(branch[0].attachments[0].type, "image")


if __name__ == "__main__":
    unittest.main()
