"""CLI launcher (TICKET-002-L, Phase 5). Owns the Playwright session.

Usage:
    python -m core.profiler.run --url https://foo.ai/ [--resume] [--fresh]
                                 [--chats 5] [--out profiler_output/]

Output: provider_profile.json + preset_matrix.json + validation_report.md
plus profiler_checkpoint.jsonl. Never touches config.json /
custom_presets.json and never imports analysis/*.
"""

import argparse
import datetime
import json
import os
import sys

from core.profiler import checkpoint as checkpoint_mod
from core.profiler import matrix as matrix_mod
from core.profiler import orchestrator
from core.profiler import validation as validation_mod
from core.profiler.profile_schema import ProviderProfile, profile_to_dict, validate_profile

DEFAULT_OUT_DIR = "profiler_output"
SEED_CATALOG = os.path.join("presets", "seed_presets.json")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Provider Profiler (TICKET-002-L)")
    parser.add_argument("--url", required=True, help="Provider URL to profile")
    parser.add_argument("--provider", default="", help="Provider id (default: URL host)")
    parser.add_argument("--resume", action="store_true", help="skip Completed bindings")
    parser.add_argument("--fresh", action="store_true", help="wipe checkpoint first")
    parser.add_argument("--chats", type=int, default=validation_mod.DEFAULT_CHATS)
    parser.add_argument("--out", default=DEFAULT_OUT_DIR)
    parser.add_argument("--login-timeout", type=int, default=600)
    parser.add_argument("--cdp", default="",
                        help="Attach to a running Chrome via CDP "
                             "(e.g. http://127.0.0.1:9222) instead of "
                             "launching a fresh browser. The attached "
                             "browser is never closed, only our page.")
    return parser.parse_args(argv)


def _provider_id(name: str, url: str) -> str:
    if name and name.strip():
        return name.strip()
    try:
        from urllib.parse import urlparse

        host = (urlparse(url or "").hostname or "provider").lower()
        return host.replace("www.", "")
    except Exception:
        return "provider"


def _resolve_storage_dir() -> str:
    """Mirror App._resolve_storage without importing main (no webview)."""
    if getattr(sys, "frozen", False):
        primary = os.path.dirname(os.path.abspath(sys.executable))
    else:
        primary = os.getcwd()
    if os.access(primary, os.W_OK):
        return primary
    return os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "AIChatExporter",
    )


def _read_preset_list(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _load_catalog() -> list:
    """Seed catalog + user catalog (read-only): seed first, user overrides by id."""
    seed = _read_preset_list(SEED_CATALOG)
    if seed is None:
        seed = _read_preset_list(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..",
            "presets", "seed_presets.json")) or []
    user = _read_preset_list(os.path.join(_resolve_storage_dir(),
                                          "custom_presets.json")) or []
    merged = {}
    for preset in list(seed) + list(user):
        if isinstance(preset, dict) and preset.get("id"):
            merged[preset["id"]] = preset
    return list(merged.values())


def _chat_targets_from_observations(observations: dict, n_chats: int) -> list:
    """Frozen snapshot of validation targets (stable index; pure).

    One snapshot is taken after probing and never re-sliced: ``index``
    refers to the position inside this frozen ``chat_items`` list, so
    ``--resume`` reopens the same element instead of a reshuffled one.
    Button lists (``href == ""``) are kept as ``index:N`` targets.
    """
    limit = max(validation_mod.MIN_CHATS, int(n_chats or 0))
    selector = observations.get("chat_list_selector", "") or ""
    targets = []
    seen = set()
    for pos, item in enumerate(observations.get("chat_items") or []):
        if not isinstance(item, dict):
            continue
        href = item.get("href", "") or ""
        try:
            idx = int(item.get("index", pos))
        except Exception:
            idx = pos
        token = checkpoint_mod.target_token(href, idx)
        if token in seen:
            continue
        seen.add(token)
        targets.append({"token": token, "href": href, "index": idx,
                        "selector": selector,
                        "text": (item.get("text", "") or "")[:200]})
        if len(targets) >= limit:
            break
    return targets


def pending_for_candidate(chat_targets: list, n_chats: int, done: dict,
                          provider_url: str, candidate_id: str) -> list:
    """Targets still Pending for a candidate (pure; resume semantics)."""
    limit = max(validation_mod.MIN_CHATS, int(n_chats or 0))
    pending = []
    for target in list(chat_targets or [])[:limit]:
        token = target.get("token", "") if isinstance(target, dict) else str(target or "")
        if not checkpoint_mod.is_completed(done, provider_url, candidate_id, token):
            pending.append(target)
    return pending


def _best_message(observations: dict) -> str:
    roles = observations.get("roles") or {}
    if isinstance(roles, dict) and roles.get("message"):
        return roles.get("message", "")
    hits = observations.get("message_hits") or {}
    if isinstance(hits, dict) and hits:
        return next(iter(hits))
    return ""


def _build_profile(provider: str, url: str, observations: dict) -> ProviderProfile:
    nav = observations.get("navigation") or {}
    roles = observations.get("roles") or {}
    title = observations.get("title") or {}
    scroll = observations.get("scroll") or {}
    chat_hits = observations.get("chat_list_hits") or {}
    evidence_n = 0
    if isinstance(chat_hits, dict):
        try:
            evidence_n = sum(int(v or 0) for v in chat_hits.values())
        except Exception:
            evidence_n = 0
    return ProviderProfile(
        provider=provider,
        provider_url=url,
        navigation={
            "type": nav.get("type", "goto"),
            "spa": bool(nav.get("spa", False)),
            "hydration_required": bool(nav.get("hydration_required", False)),
            "wait_after_navigation_ms": nav.get("wait_after_navigation_ms", 2000),
        },
        chat_list={
            "kind": "mixed",  # finalized from the matrix (links|buttons|mixed)
            "selector": observations.get("chat_list_selector", "") or "",
            "evidence_N": evidence_n,
        },
        chat={"container": scroll.get("container", "") or ""},
        messages={
            "user": roles.get("user", "") or "",
            "assistant": roles.get("assistant", "") or "",
            "message": _best_message(observations),
        },
        title={"source": title.get("source", "text"), "selector": title.get("selector", "") or ""},
        extraction={"viable": []},
        scroll={
            "required": bool(scroll.get("required", False)),
            "container": scroll.get("container", "") or "",
            "infinite": bool(scroll.get("infinite", False)),
        },
        checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


def _open_session(pw, cdp_endpoint: str = ""):
    """Open (browser, page, owned) for the profiler session (smoke-only).

    With ``--cdp`` the launcher attaches to an already-running Chrome
    (trusted profile, Google login works) via ``connect_over_cdp`` and
    takes a tab from its first context — the same pattern as the App
    workers (``main._cdp_browser`` + ``contexts[0].new_page()``).
    ``owned=False`` means the browser belongs to the user and must never
    be closed. Without ``--cdp`` the previous launch behaviour is kept
    bit-for-bit (``owned=True``).
    """
    if (cdp_endpoint or "").strip():
        endpoint = cdp_endpoint.strip()
        try:
            browser = pw.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            raise RuntimeError(
                f"CDP unavailable at {endpoint}: start Chrome with "
                f"--remote-debugging-port=9222 first ({e})")
        try:
            contexts = browser.contexts
        except Exception:
            contexts = []
        if contexts:
            page = contexts[0].new_page()
        else:
            page = browser.new_page()
        return browser, page, False
    browser = pw.chromium.launch(headless=False)
    return browser, browser.new_page(), True


def _close_session(browser, page, owned: bool) -> None:
    """Teardown guard: our browser -> close it; чужой -> close only the page."""
    try:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if owned and browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    except Exception:
        pass


def _write_validation_report(path: str, matrix: dict, validations: list) -> None:
    lines = ["# Profiler validation report", ""]
    matrix = matrix if isinstance(matrix, dict) else {}
    candidates = matrix.get("candidates", []) if isinstance(matrix, dict) else []
    lines.append(f"## Preset matrix ({len(candidates)} candidates)")
    for cand in candidates:
        kind = cand.get("kind", "?")
        cid = cand.get("preset_id") or (cand.get("preset") or {}).get("id", "?")
        probes = cand.get("probes", {})
        lines.append(f"- {kind} {cid} probes={probes}")
    lines.append("")
    # B3: provider-level Blocked always reaches the artifact, even when no
    # candidate exists to carry it (canonical Perplexity: candidates == []).
    blocked = matrix.get("blocked") if isinstance(matrix, dict) else None
    if isinstance(blocked, dict) and blocked.get("reason"):
        lines.append(f"## Provider-level Blocked ({blocked.get('reason')})")
        lines.append(f"evidence={blocked.get('evidence', {})}")
        lines.append("")
    if not candidates and not (isinstance(blocked, dict) and blocked.get("reason")):
        lines.append("## No candidates (all Incompatible/Blocked, see profile)")
        lines.append("")
    for validation in validations:
        cid = validation.get("candidate_id", "?")
        summary = validation.get("summary", {})
        lines.append(f"## {cid}")
        lines.append(
            f"total {summary.get('total', 0)} | "
            f"Compatible {summary.get('Compatible', 0)} / "
            f"Partial {summary.get('Partial', 0)} / "
            f"Blocked {summary.get('Blocked', 0)} / "
            f"Incompatible {summary.get('Incompatible', 0)}"
        )
        if validation.get("skipped"):
            lines.append(f"- skipped: {validation.get('skipped')}")
        for item in validation.get("per_chat", []):
            ev = item.get("evidence", {})
            lines.append(
                f"- {item.get('verdict')} ({item.get('reason')}) "
                f"{item.get('chat_url')} chats={ev.get('chats')} "
                f"msgs={ev.get('messages')} user={ev.get('user')} "
                f"asst={ev.get('assistant')}"
            )
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None) -> int:
    args = _parse_args(argv)
    n_chats = max(validation_mod.MIN_CHATS, int(args.chats or 0))
    out_dir = args.out or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    ckpt_path = checkpoint_mod.checkpoint_path(out_dir)
    if args.fresh:
        try:
            os.remove(ckpt_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"cannot wipe checkpoint: {e}", file=sys.stderr)
            return 2
    done: dict = {}
    if args.resume:
        done, ignored = checkpoint_mod.load_completed(ckpt_path)
        if checkpoint_mod.has_legacy_records(ckpt_path) and not done:
            print("checkpoint v1 incompatible with target_token schema v2; "
                  "rerun with --fresh (no migration).", file=sys.stderr)
            return 2
        if ignored:
            print(f"[profiler] resume: ignored {ignored} legacy record(s).")
    elif os.path.exists(ckpt_path) and checkpoint_mod.has_legacy_records(ckpt_path):
        print("checkpoint v1 incompatible with target_token schema v2; "
              "rerun with --fresh (no migration).", file=sys.stderr)
        return 2

    from playwright.sync_api import sync_playwright

    provider = _provider_id(args.provider, args.url)
    catalog = _load_catalog()
    with sync_playwright() as pw:
        try:
            browser, page, owned = _open_session(pw, args.cdp)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 2
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        if owned:
            print("Log in once in the opened window, then press Enter here...")
        else:
            print("Attached via CDP: log in in YOUR Chrome window if needed, "
                  "then press Enter here...")
        try:
            input()
        except EOFError:
            pass
        obs = orchestrator.run_probes(page, args.url, log=print)
        goto_empty = bool((obs.get("navigation") or {}).get("goto_empty", False))
        profile = _build_profile(provider, args.url, obs)
        ok, errors = validate_profile(profile)
        if not ok:
            print(f"invalid profile: {errors}", file=sys.stderr)
            _close_session(browser, page, owned)
            return 2
        matrix = matrix_mod.build_preset_matrix(
            provider, obs, catalog, goto_empty=goto_empty)
        profile.chat_list["kind"] = matrix.get("chat_list_kind", "mixed")
        profile.extraction["viable"] = [c.get("kind", "") for c in matrix["candidates"]]
        with open(os.path.join(out_dir, "provider_profile.json"), "w",
                  encoding="utf-8") as f:
            json.dump(profile_to_dict(profile), f, ensure_ascii=False, indent=2)
        with open(os.path.join(out_dir, "preset_matrix.json"), "w",
                  encoding="utf-8") as f:
            json.dump(matrix, f, ensure_ascii=False, indent=2)

        targets = _chat_targets_from_observations(obs, n_chats)
        blocked = obs.get("blocked") or {}
        blocked_reason = blocked.get("reason", "") if isinstance(blocked, dict) else ""
        blocked_evidence = blocked.get("evidence", {}) if isinstance(blocked, dict) else {}

        # Return to the home page so every candidate can re-scan its chat list.
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass

        validations = []
        run_error = ""
        try:
            for cand in matrix.get("candidates", []):
                cid = cand.get("preset_id") or (cand.get("preset") or {}).get("id", "?")
                pending = pending_for_candidate(targets, n_chats, done, args.url, cid)
                if not targets:
                    validations.append({
                        "candidate_id": cid, "per_chat": [],
                        "summary": verdicts_empty_summary(),
                        "skipped": "no-chats"})
                    continue
                if args.resume and not pending:
                    validations.append({
                        "candidate_id": cid, "per_chat": [],
                        "summary": verdicts_empty_summary(),
                        "skipped": "completed"})
                    continue
                report = validation_mod.validate_candidate(
                    page, cand, pending, catalog, default_url=args.url, log=print,
                    n_chats=n_chats, blocked_reason=blocked_reason,
                    blocked_evidence=blocked_evidence)
                validations.append(report)
                for item in report.get("per_chat", []):
                    target = item.get("target") or {}
                    checkpoint_mod.append_record(ckpt_path, {
                        "provider_url": args.url, "candidate_id": cid,
                        "target_token": item.get("chat_url", ""),
                        "chat_url": target.get("href", "") or "",
                        "index": target.get("index", 0),
                        "selector": target.get("selector", "") or "",
                        "verdict": item.get("verdict", ""),
                        "reason": item.get("reason", ""),
                    })
        except Exception as e:
            run_error = str(e)
            print(f"[profiler] validation failed: {e}", file=sys.stderr)
        finally:
            if run_error and not validations:
                validations.append({
                    "candidate_id": "?", "per_chat": [],
                    "summary": verdicts_empty_summary(),
                    "skipped": f"error: {run_error}"})
            _write_validation_report(
                os.path.join(out_dir, "validation_report.md"), matrix,
                validations)
            # N4: no re-read/rewrite of preset_matrix.json here — blocked is
            # already in the in-memory matrix (build_preset_matrix) and was
            # written before validation; a second IO pass only risks races
            # on a shared --out dir.
            _close_session(browser, page, owned)
    print(f"done: {out_dir}/provider_profile.json + preset_matrix.json + validation_report.md")
    return 0


def verdicts_empty_summary() -> dict:
    return {"total": 0, "Compatible": 0, "Partial": 0,
            "Incompatible": 0, "Blocked": 0}


if __name__ == "__main__":
    raise SystemExit(main())
