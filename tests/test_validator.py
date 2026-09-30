import unittest

from conversation.models import ConversationModel, ConversationTree, Message, TreeNode
from conversation.validator import (
    validate_all,
    validate_roles,
    validate_structure,
    validate_tree,
)


def _model(messages, tree=None, title="T", source_url="https://x"):
    return ConversationModel(
        source="gemini", stable_id="c", title=title, source_url=source_url,
        messages=messages, tree=tree,
    )


class ValidatorTest(unittest.TestCase):
    def test_validate_all_ok(self):
        model = _model([Message(role="user", content="q"), Message(role="assistant", content="a")])
        res = validate_all(model)
        self.assertTrue(res.ok)
        self.assertEqual(res.errors, [])

    def test_too_few_messages(self):
        model = _model([Message(role="user", content="q")])
        res = validate_all(model)
        self.assertFalse(res.ok)
        self.assertTrue(any("too few messages" in e for e in res.errors))

    def test_missing_user(self):
        model = _model([Message(role="assistant", content="a"), Message(role="assistant", content="b")])
        res = validate_roles(model)
        self.assertFalse(res.ok)
        self.assertTrue(any("no user messages" in e for e in res.errors))

    def test_invalid_role(self):
        model = _model([Message(role="user", content="q"), Message(role="bogus", content="x")])
        res = validate_roles(model)
        self.assertTrue(any("invalid roles" in e for e in res.errors))

    def test_tree_cycle_detected(self):
        nodes = {
            "a": TreeNode(id="a", message=Message(role="user", content="q"), parent_id="b", children_ids=["b"]),
            "b": TreeNode(id="b", message=Message(role="assistant", content="a"), parent_id="a", children_ids=["a"]),
        }
        tree = ConversationTree(nodes=nodes, root_id="a", active_node_id="b")
        model = _model(
            [Message(role="user", content="q"), Message(role="assistant", content="a")],
            tree=tree,
        )
        res = validate_tree(model)
        self.assertFalse(res.ok)
        self.assertTrue(any("cycle" in e for e in res.errors))

    def test_structure_warnings_for_empty_title(self):
        model = _model([Message(role="user", content="q"), Message(role="assistant", content="a")], title="")
        res = validate_structure(model)
        self.assertTrue(res.ok)
        self.assertTrue(any("title is empty" in w for w in res.warnings))


if __name__ == "__main__":
    unittest.main()
