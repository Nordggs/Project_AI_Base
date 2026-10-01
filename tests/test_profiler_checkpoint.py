"""Tests: checkpoint v2 resume/fresh semantics (TICKET-002-L, Phase 4)."""

from core.profiler import checkpoint as checkpoint_mod


def test_resume_skips_completed(tmp_path):
    path = str(tmp_path / "profiler_checkpoint.jsonl")
    checkpoint_mod.append_record(path, {"provider_url": "https://foo.ai/",
                                        "candidate_id": "c1",
                                        "target_token": "https://foo.ai/c/1",
                                        "chat_url": "https://foo.ai/c/1"})
    done, ignored = checkpoint_mod.load_completed(path)
    assert ignored == 0
    assert checkpoint_mod.is_completed(done, "https://foo.ai/", "c1",
                                       "https://foo.ai/c/1")
    assert not checkpoint_mod.is_completed(done, "https://foo.ai/", "c1",
                                           "https://foo.ai/c/2")


def test_broken_lines_skipped(tmp_path):
    path = str(tmp_path / "profiler_checkpoint.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write("not-json\n")
        f.write('{"provider_url": "https://foo.ai/", "candidate_id": "c1",'
                ' "chat_url": "https://foo.ai/c/1"}\n')
    done, ignored = checkpoint_mod.load_completed(path)
    assert done == {}
    assert ignored == 2  # broken line + legacy v1 record (no migration)


def test_missing_file_empty():
    assert checkpoint_mod.load_completed(
        "definitely-missing-profiler-checkpoint.jsonl") == ({}, 0)


def test_append_stamps_schema_version(tmp_path):
    path = str(tmp_path / "profiler_checkpoint.jsonl")
    checkpoint_mod.append_record(path, {"provider_url": "https://foo.ai/",
                                        "candidate_id": "c1",
                                        "target_token": "index:0"})
    done, ignored = checkpoint_mod.load_completed(path)
    assert ignored == 0
    assert checkpoint_mod.is_completed(done, "https://foo.ai/", "c1", "index:0")
