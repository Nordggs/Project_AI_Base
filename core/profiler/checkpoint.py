"""Checkpoint / resume (TICKET-002-L, Phase 4). Pure JSONL helpers, no browser.

Schema v2 (target-driven): binding key is
``(provider_url, candidate_id, target_token)`` where
``target_token = href (http) | "index:N"``. Records carry
``schema_version: 2``. Files/records without ``schema_version == 2``
are legacy (v1, ``chat_url`` semantics) and are NEVER silently mixed:
``load_completed`` reports them via the ``ignored_legacy`` counter and the
caller must refuse a non-fresh run over a legacy file. No migration:
rerun with ``--fresh``.
"""

import json
import os

SCHEMA_VERSION = 2


def checkpoint_path(out_dir: str) -> str:
    return os.path.join(out_dir or ".", "profiler_checkpoint.jsonl")


def target_token(href: str = "", index=None) -> str:
    href = href or ""
    if href.startswith("http"):
        return href
    try:
        return f"index:{int(index)}"
    except Exception:
        return "index:0"


def record_key(provider_url: str, candidate_id: str, token: str) -> str:
    return f"{provider_url or ''}\x00{candidate_id or ''}\x00{token or ''}"


def append_record(path: str, record: dict) -> None:
    rec = dict(record or {})
    rec["schema_version"] = SCHEMA_VERSION
    if not rec.get("target_token") and rec.get("chat_url"):
        rec["target_token"] = rec["chat_url"]
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_completed(path: str) -> "tuple[dict, int]":
    """Load checkpoint file -> (done_v2, ignored_legacy).

    Only ``schema_version == 2`` records with a ``target_token`` enter
    ``done``. Everything else (v1 records, broken lines) is counted in
    ``ignored_legacy`` / skipped. Never raises.
    """
    done: dict = {}
    ignored = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    ignored += 1
                    continue
                if not isinstance(rec, dict):
                    ignored += 1
                    continue
                if rec.get("schema_version") != SCHEMA_VERSION:
                    ignored += 1
                    continue
                token = rec.get("target_token", "") or ""
                if not token:
                    ignored += 1
                    continue
                key = record_key(
                    rec.get("provider_url", ""),
                    rec.get("candidate_id", ""),
                    token,
                )
                done[key] = rec
    except FileNotFoundError:
        return {}, 0
    except Exception:
        return dict(done), ignored
    return done, ignored


def has_legacy_records(path: str) -> bool:
    """True when the file holds any non-v2 record (v1 or broken)."""
    _, ignored = load_completed(path)
    if ignored:
        return True
    try:
        return os.path.getsize(path) > 0 and not load_completed(path)[0]
    except Exception:
        return False


def is_completed(done: dict, provider_url: str, candidate_id: str, token: str) -> bool:
    if not isinstance(done, dict):
        return False
    return record_key(provider_url, candidate_id, token) in done
