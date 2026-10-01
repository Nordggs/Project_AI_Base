"""Tests: resume pending selection on target tokens (TICKET-002-L, R1)."""

from core.profiler import checkpoint as checkpoint_mod
from core.profiler import run as run_mod


def _targets(*tokens):
    return [{"token": t, "href": t if t.startswith("http") else "",
             "index": i, "selector": "nav button", "text": ""}
            for i, t in enumerate(tokens)]


def test_pending_skips_completed(tmp_path):
    path = str(tmp_path / "profiler_checkpoint.jsonl")
    checkpoint_mod.append_record(path, {
        "provider_url": "https://foo.ai/", "candidate_id": "c1",
        "target_token": "https://foo.ai/c/1",
    })
    done, _ = checkpoint_mod.load_completed(path)
    pending = run_mod.pending_for_candidate(
        _targets("https://foo.ai/c/1", "https://foo.ai/c/2",
                 "https://foo.ai/c/3"),
        3, done, "https://foo.ai/", "c1")
    assert [t["token"] for t in pending] == ["https://foo.ai/c/2",
                                             "https://foo.ai/c/3"]


def test_pending_all_completed_is_empty(tmp_path):
    path = str(tmp_path / "profiler_checkpoint.jsonl")
    for tok in ("index:0", "index:1", "index:2"):
        checkpoint_mod.append_record(path, {
            "provider_url": "https://foo.ai/", "candidate_id": "c1",
            "target_token": tok,
        })
    done, _ = checkpoint_mod.load_completed(path)
    pending = run_mod.pending_for_candidate(
        _targets("index:0", "index:1", "index:2"), 3, done,
        "https://foo.ai/", "c1")
    assert pending == []


def test_pending_respects_minimum_n():
    # --chats below the floor is clamped to MIN_CHATS (3).
    pending = run_mod.pending_for_candidate(
        _targets("a", "b", "c", "d"), 2, {}, "https://foo.ai/", "c1")
    assert [t["token"] for t in pending] == ["a", "b", "c"]


def test_targets_keep_button_items_without_href():
    obs = {"chat_list_selector": "nav button",
           "chat_items": [{"index": 0, "href": "", "text": "chat one"},
                          {"index": 1, "href": "", "text": "chat two"}]}
    targets = run_mod._chat_targets_from_observations(obs, 5)
    assert [t["token"] for t in targets] == ["index:0", "index:1"]
    assert all(t["selector"] == "nav button" for t in targets)
