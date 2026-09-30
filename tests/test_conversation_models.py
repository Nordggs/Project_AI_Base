import unittest

from conversation.models import (
    AttachmentNode,
    ConversationModel,
    ConversationTree,
    Message,
    TreeNode,
)
from conversation.serializer import model_to_dict


def _msg(role, content, **kw):
    return Message(role=role, content=content, **kw)


class AttachmentNodeTest(unittest.TestCase):
    def test_dict_access(self):
        a = AttachmentNode(type="image", mime="image/png")
        self.assertEqual(a["type"], "image")
        self.assertEqual(a.get("mime"), "image/png")
        a["name"] = "x.png"
        self.assertEqual(a["name"], "x.png")
        self.assertEqual(a.pop("name"), "x.png")
        self.assertIsNone(a.get("name"))
        self.assertEqual(a.get("missing", "dflt"), "dflt")

    def test_getitem_on_missing_meta_key(self):
        a = AttachmentNode()
        self.assertEqual(a.get("meta"), {})
        with self.assertRaises(KeyError):
            a["nope"]


class MessageTest(unittest.TestCase):
    def test_renderable_with_content(self):
        self.assertTrue(_msg("user", "hello").is_renderable())

    def test_renderable_with_only_attachment(self):
        m = Message(role="assistant", content="", attachments=[AttachmentNode(type="image")])
        self.assertTrue(m.is_renderable())

    def test_not_renderable_when_empty(self):
        self.assertFalse(_msg("assistant", "").is_renderable())


class ConversationTreeTest(unittest.TestCase):
    def _tree(self):
        nodes = {
            "r": TreeNode(id="r", message=None, children_ids=["a"]),
            "a": TreeNode(id="a", message=_msg("user", "hello"), parent_id="r", children_ids=["b"]),
            "b": TreeNode(id="b", message=_msg("assistant", "world"), parent_id="a", children_ids=[]),
        }
        return ConversationTree(nodes=nodes, root_id="r", active_node_id="b")

    def test_active_branch_ordered_and_filtered(self):
        tree = self._tree()
        msgs = tree.get_active_branch()
        self.assertEqual([m.content for m in msgs], ["hello", "world"])

    def test_active_branch_filters_non_renderable(self):
        tree = self._tree()
        tree.nodes["a"].message = _msg("user", "")  # empty → filtered
        msgs = tree.get_active_branch()
        self.assertEqual([m.content for m in msgs], ["world"])

    def test_active_branch_empty_without_active_node(self):
        tree = ConversationTree(nodes={}, root_id=None, active_node_id=None)
        self.assertEqual(tree.get_active_branch(), [])

    def test_active_branch_cycle_guarded(self):
        nodes = {
            "a": TreeNode(id="a", message=_msg("user", "x"), parent_id="b", children_ids=["b"]),
            "b": TreeNode(id="b", message=_msg("assistant", "y"), parent_id="a", children_ids=["a"]),
        }
        tree = ConversationTree(nodes=nodes, root_id="a", active_node_id="b")
        msgs = tree.get_active_branch()
        self.assertEqual(len(msgs), 2)

    def test_all_branches(self):
        nodes = {
            "r": TreeNode(id="r", message=None, children_ids=["a", "c"]),
            "a": TreeNode(id="a", message=_msg("user", "q1"), parent_id="r", children_ids=["b"]),
            "b": TreeNode(id="b", message=_msg("assistant", "a1"), parent_id="a", children_ids=[]),
            "c": TreeNode(id="c", message=_msg("user", "q2"), parent_id="r", children_ids=["d"]),
            "d": TreeNode(id="d", message=_msg("assistant", "a2"), parent_id="c", children_ids=[]),
        }
        tree = ConversationTree(nodes=nodes, root_id="r", active_node_id="b")
        branches = tree.get_all_branches()
        contents = [[m.content for m in b] for b in branches]
        self.assertIn(["q1", "a1"], contents)
        self.assertIn(["q2", "a2"], contents)


class ConversationModelTest(unittest.TestCase):
    def test_to_dict(self):
        att = AttachmentNode(type="image", mime="image/png", name="a.png")
        model = ConversationModel(
            source="chatgpt",
            stable_id="cid123",
            title="T",
            source_url="https://x",
            messages=[Message(role="user", content="hi", timestamp=1.0, attachments=[att])],
        )
        d = model_to_dict(model)
        self.assertEqual(d["chat_id"], "cid123")
        self.assertEqual(d["messages"][0]["attachments"][0]["type"], "image")

    def test_to_dict_with_tree(self):
        nodes = {
            "r": TreeNode(id="r", message=None, children_ids=["a"]),
            "a": TreeNode(id="a", message=_msg("user", "hi"), parent_id="r", children_ids=[]),
        }
        tree = ConversationTree(nodes=nodes, root_id="r", active_node_id="a")
        model = ConversationModel(
            source="chatgpt", stable_id="c", title="T", source_url="u",
            messages=[_msg("user", "hi")], tree=tree,
        )
        d = model_to_dict(model)
        self.assertIn("nodes", d["tree"])
        self.assertEqual(d["tree"]["root_id"], "r")


if __name__ == "__main__":
    unittest.main()
