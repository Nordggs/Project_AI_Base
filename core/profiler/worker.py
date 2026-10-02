"""ProfilerWorker (TICKET-003, Phase B). UI-driven wrapper over the engine.

Owns a background thread with its own Playwright lifecycle and drives the
same public engine probes as the CLI (``core.profiler.run.main``) step by
step, so the UI can report phases without parsing logs and without
modifying engine files (orchestrator/validation/matrix/checkpoint).

Critical invariants:
  - a foreign (CDP-attached) browser is NEVER closed — only our own page
    is closed via ``run._close_session(browser, page, owned)``;
  - no cookies / credentials / session tokens are ever written anywhere
    by this worker (observations and results stay in memory; only the
    checkpoint JSONL with verdict records goes to ``storage_dir``).

Cancel is cooperative: the flag is checked between candidates and phases.
It is deliberately NOT threaded into ``validate_candidate`` (that would
change engine behaviour — one list_chats scan per candidate, L2); a cancel
during validation takes effect after the current candidate finishes.
"""

import os
import threading
import time

from core.profiler import checkpoint as checkpoint_mod
from core.profiler import matrix as matrix_mod
from core.profiler import orchestrator
from core.profiler import run as run_mod
from core.profiler import validation as validation_mod
from core.profiler import verdicts
from core.profiler.profile_schema import profile_to_dict, validate_profile

__all__ = [
    "PHASE_IDLE",
    "PHASE_DISCOVERING",
    "PHASE_FINDING_CHATS",
    "PHASE_TESTING_NAVIGATION",
    "PHASE_VALIDATING",
    "PHASE_BUILDING_MATRIX",
    "PHASE_AWAITING_LOGIN",
    "PHASE_COMPLETED",
    "PHASE_FAILED",
    "PHASE_CANCELLED",
    "ProfilerWorker",
    "assemble_observations",
    "is_login_block_page",
]

PHASE_IDLE = "idle"
PHASE_DISCOVERING = "discovering"
PHASE_FINDING_CHATS = "finding_chats"
PHASE_TESTING_NAVIGATION = "testing_navigation"
PHASE_VALIDATING = "validating"
PHASE_BUILDING_MATRIX = "building_matrix"
PHASE_AWAITING_LOGIN = "awaiting_login"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"
PHASE_CANCELLED = "cancelled"

# UI phase labels (§10 ticket) mapped from internal phases.
PHASE_LABELS = {
    PHASE_DISCOVERING: "Discovering",
    PHASE_FINDING_CHATS: "Finding chats",
    PHASE_TESTING_NAVIGATION: "Testing navigation",
    PHASE_VALIDATING: "Validating candidates",
    PHASE_BUILDING_MATRIX: "Building matrix",
    PHASE_COMPLETED: "Completed",
}

DEFAULT_LOGIN_TIMEOUT_S = 600

# Google answers automation-controlled browsers with its "browser or app
# may not be secure" page (OAuth Error 403: disallowed_useragent). Probing
# further is pointless — fail fast with actionable instructions instead
# of a cryptic no-chats result.
_LOGIN_BLOCK_HOST = "accounts.google."
_LOGIN_BLOCK_PHRASES = (
    "этот браузер или приложение небезопасны",
    "this browser or app may not be secure",
    "try using a different browser",
    "смените браузер",
    "couldn't sign you in",
    "не удалось войти",
    "disallowed_useragent",
)


def is_login_block_page(url, text):
    """True when the page is Google's automation-login block (pure).

    Gated on a Google accounts host (or the disallowed_useragent marker,
    which only Google emits) so ordinary pages merely quoting the text
    never match. Never raises.
    """
    try:
        page_url = (url or "").lower()
        body = (text or "").lower()
        if "disallowed_useragent" in body:
            return True
        if _LOGIN_BLOCK_HOST not in page_url:
            return False
        return any(phrase in body for phrase in _LOGIN_BLOCK_PHRASES)
    except Exception:
        return False


def assemble_observations(provider_url, chat, nav, opened,
                          message_hits, roles, title, scroll):
    """Build the obs dict with exactly the run_probes() composition.

    Same 12 keys (provider_url, navigation, chat_open, chat_list_hits,
    chat_list_selector, chat_items, empty_title_links, message_hits,
    roles, title, scroll, blocked) including the
    ``_detect_product_filter(empty_title, best_sel)`` Blocked path, so
    worker behaviour stays identical to ``run.main``.
    """
    chat = chat if isinstance(chat, dict) else {}
    blocked = orchestrator._detect_product_filter(
        chat.get("empty_title") or {}, chat.get("best_sel") or "")
    return {
        "provider_url": provider_url,
        "navigation": nav if isinstance(nav, dict) else {},
        "chat_open": bool(opened),
        "chat_list_hits": chat.get("hits") or {},
        "chat_list_selector": chat.get("best_sel") or "",
        "chat_items": chat.get("items") or [],
        "empty_title_links": chat.get("empty_title") or {},
        "message_hits": message_hits if isinstance(message_hits, dict) else {},
        "roles": roles if isinstance(roles, dict) else {},
        "title": title if isinstance(title, dict) else {},
        "scroll": scroll if isinstance(scroll, dict) else {},
        "blocked": blocked,
    }


class ProfilerWorker:
    """Background profiler run: own thread, own Playwright session."""

    def __init__(self, storage_dir, log=None, cdp_endpoint="",
                 playwright_factory=None, catalog=None, seed_path="",
                 login_timeout=DEFAULT_LOGIN_TIMEOUT_S):
        self._storage_dir = storage_dir
        self._log = log or (lambda msg: None)
        self._cdp_endpoint = (cdp_endpoint or "").strip()
        self._playwright_factory = playwright_factory
        self._catalog = catalog
        self._seed_path = seed_path or ""
        self._login_timeout = max(1, int(login_timeout or 0))
        self._lock = threading.Lock()
        self._thread = None
        self._cancel_flag = False
        self._login_event = threading.Event()
        self._status = {
            "phase": PHASE_IDLE,
            "detail": "",
            "candidates_done": 0,
            "candidates_total": 0,
            "chat_current": 0,
            "chat_total": 0,
            "awaiting_login": False,
            "error": "",
        }
        self._results = None

    # -- public control -------------------------------------------------

    def is_running(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, url, provider="", n_chats=validation_mod.DEFAULT_CHATS,
              resume=False, fresh=False):
        """Start a profiling run in a daemon thread. Returns the thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("profiler already running")
            self._cancel_flag = False
            self._login_event.clear()
            self._results = None
            self._status = {
                "phase": PHASE_DISCOVERING,
                "detail": (url or "").strip(),
                "candidates_done": 0,
                "candidates_total": 0,
                "chat_current": 0,
                "chat_total": 0,
                "awaiting_login": False,
                "error": "",
            }
            thread = threading.Thread(
                target=self._run,
                args=((url or "").strip(), (provider or "").strip(),
                      max(validation_mod.MIN_CHATS, int(n_chats or 0)),
                      bool(resume), bool(fresh)),
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return thread

    def cancel(self):
        """Request cooperative stop; wakes a login wait as well."""
        with self._lock:
            self._cancel_flag = True
            self._login_event.set()

    def continue_after_login(self):
        """Resume after the user logged in (or chose to continue anyway)."""
        self._login_event.set()

    def has_resume(self, url):
        """True if the checkpoint holds v2 records for this provider URL."""
        try:
            path = checkpoint_mod.checkpoint_path(self._storage_dir)
            done, _ignored = checkpoint_mod.load_completed(path)
        except Exception:
            return False
        url = (url or "").strip()
        if not url or not isinstance(done, dict):
            return False
        prefix = url + "\x00"
        try:
            return any(str(key).startswith(prefix) for key in done)
        except Exception:
            return False

    def get_status(self):
        with self._lock:
            status = dict(self._status)
        status["label"] = PHASE_LABELS.get(status.get("phase", ""),
                                           status.get("phase", ""))
        return status

    def get_results(self):
        with self._lock:
            return self._results

    # -- internals ------------------------------------------------------

    def _cancelled(self):
        with self._lock:
            return self._cancel_flag

    def _detect_login_block(self, page):
        """Check the live page for Google's automation-login block."""
        try:
            page_url = page.url or ""
        except Exception:
            return False
        try:
            text = page.evaluate("document.documentElement.innerText") or ""
        except Exception:
            text = ""
        return is_login_block_page(page_url, text if isinstance(text, str) else "")

    def _set_status(self, **fields):
        with self._lock:
            self._status.update(fields)

    def _phase(self, phase, detail=""):
        self._set_status(phase=phase, detail=detail,
                         awaiting_login=(phase == PHASE_AWAITING_LOGIN))
        self._log(f"[profiler] {PHASE_LABELS.get(phase, phase)}"
                  + (f": {detail}" if detail else ""))

    def _open_playwright(self):
        if self._playwright_factory is not None:
            return self._playwright_factory()
        from playwright.sync_api import sync_playwright
        return sync_playwright()

    def _load_catalog(self):
        if self._catalog is not None:
            return list(self._catalog)
        return run_mod._load_catalog_from(self._storage_dir, self._seed_path)

    def _run(self, url, provider, n_chats, resume, fresh):
        ckpt_path = checkpoint_mod.checkpoint_path(self._storage_dir)
        if fresh:
            try:
                os.remove(ckpt_path)
            except FileNotFoundError:
                pass
            except Exception as exc:
                self._finish_failed(f"cannot wipe checkpoint: {exc}")
                return
        done = {}
        if resume:
            try:
                done, _ignored = checkpoint_mod.load_completed(ckpt_path)
            except Exception as exc:
                self._finish_failed(f"cannot read checkpoint: {exc}")
                return
            # Parity with run.main: v1 records have no target_token (no migration).
            if checkpoint_mod.has_legacy_records(ckpt_path) and not done:
                self._finish_failed(
                    "checkpoint v1 incompatible with target_token schema v2; "
                    "rerun fresh (no migration).")
                return
        elif os.path.exists(ckpt_path) and checkpoint_mod.has_legacy_records(ckpt_path):
            self._finish_failed(
                "checkpoint v1 incompatible with target_token schema v2; "
                "rerun fresh (no migration).")
            return

        provider_id = run_mod._provider_id(provider, url)
        try:
            catalog = self._load_catalog()
        except Exception as exc:
            self._finish_failed(f"cannot load catalog: {exc}")
            return

        try:
            with self._open_playwright() as pw:
                try:
                    browser, page, owned = run_mod._open_session(
                        pw, self._cdp_endpoint)
                except RuntimeError as exc:
                    self._finish_failed(str(exc))
                    return
                try:
                    self._run_session(page, url, provider_id, n_chats,
                                      resume, done, ckpt_path, catalog)
                finally:
                    # Foreign browsers are never closed — page only.
                    run_mod._close_session(browser, page, owned)
        except Exception as exc:
            self._finish_failed(f"profiler crashed: {exc}")

    def _run_session(self, page, url, provider_id, n_chats, resume,
                     done, ckpt_path, catalog):
        if self._cancelled():
            return self._finish_cancelled()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            self._finish_failed(f"cannot open provider URL: {exc}")
            return

        # -- finding chats (login gate) ---------------------------------
        self._phase(PHASE_FINDING_CHATS, url)
        chat = orchestrator.probe_chat_list(page, self._log)
        items = chat.get("items") if isinstance(chat, dict) else []
        if not items and not self._cancelled():
            self._phase(PHASE_AWAITING_LOGIN,
                        "Login required — log in, then Continue")
            self._login_event.wait(timeout=self._login_timeout)
            if self._cancelled():
                return self._finish_cancelled()
            # One re-probe after login (or continue-without-login); an
            # empty account simply flows into the no-chats path below.
            self._phase(PHASE_FINDING_CHATS, url)
            chat = orchestrator.probe_chat_list(page, self._log)
            if self._detect_login_block(page):
                self._finish_failed(
                    "Google заблокировал вход в этом окне "
                    "(«браузер или приложение небезопасны»): запустите Chrome "
                    "через приложение (кнопка «Запустить Chrome»), войдите "
                    "в аккаунт там и запустите профилирование заново.")
                return

        if self._cancelled():
            return self._finish_cancelled()

        # -- testing navigation ------------------------------------------
        self._phase(PHASE_TESTING_NAVIGATION)
        nav, opened = orchestrator.open_research_context(
            page, url, chat if isinstance(chat, dict) else {}, self._log)

        if self._cancelled():
            return self._finish_cancelled()

        # -- discovering --------------------------------------------------
        self._phase(PHASE_DISCOVERING)
        if opened:
            message_hits = orchestrator.probe_messages(page)
            roles = orchestrator.probe_roles(page, self._log)
            best_sel = (chat.get("best_sel") or "") if isinstance(chat, dict) else ""
            title = orchestrator.probe_title(page, best_sel, self._log)
            scroll = orchestrator.probe_scroll(page, best_sel, self._log)
        else:
            message_hits = {}
            roles = {"message": "", "user": "", "assistant": "",
                     "user_n": 0, "assistant_n": 0, "found": False}
            title = {"source": "url", "selector": ""}
            scroll = {"required": False, "container": "", "infinite": False,
                      "status": "unknown"}

        obs = assemble_observations(url, chat, nav, opened,
                                    message_hits, roles, title, scroll)

        # -- building matrix ----------------------------------------------
        self._phase(PHASE_BUILDING_MATRIX)
        profile = run_mod._build_profile(provider_id, url, obs)
        goto_empty = bool((obs.get("navigation") or {}).get("goto_empty", False))
        matrix = matrix_mod.build_preset_matrix(
            provider_id, obs, catalog, goto_empty=goto_empty)
        # Parity with run.main: reject invalid profiles, finalize kind/viable.
        ok, errors = validate_profile(profile)
        if not ok:
            self._finish_failed(f"invalid profile: {errors}")
            return
        profile.chat_list["kind"] = matrix.get("chat_list_kind", "mixed")
        profile.extraction["viable"] = [c.get("kind", "")
                                        for c in matrix.get("candidates", [])]
        targets = run_mod._chat_targets_from_observations(obs, n_chats)
        blocked = obs.get("blocked") or {}
        blocked_reason = blocked.get("reason", "") if isinstance(blocked, dict) else ""
        blocked_evidence = blocked.get("evidence", {}) if isinstance(blocked, dict) else {}

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass

        candidates = matrix.get("candidates", []) if isinstance(matrix, dict) else []
        self._set_status(candidates_total=len(candidates),
                         chat_total=min(len(targets), n_chats))

        # -- validating ----------------------------------------------------
        validations = []
        run_error = ""
        try:
            for pos, cand in enumerate(candidates):
                if self._cancelled():
                    break
                cid = (cand.get("preset_id")
                       or (cand.get("preset") or {}).get("id", "?"))
                self._set_status(candidates_done=pos,
                                 detail=f"candidate {pos + 1}/{len(candidates)}: {cid}")
                pending = run_mod.pending_for_candidate(
                    targets, n_chats, done, url, cid)
                if not targets:
                    validations.append({
                        "candidate_id": cid, "per_chat": [],
                        "summary": run_mod.verdicts_empty_summary(),
                        "skipped": "no-chats"})
                    continue
                if resume and not pending:
                    validations.append({
                        "candidate_id": cid, "per_chat": [],
                        "summary": run_mod.verdicts_empty_summary(),
                        "skipped": "completed"})
                    continue
                report = validation_mod.validate_candidate(
                    page, cand, pending, catalog, default_url=url,
                    log=self._log, n_chats=n_chats,
                    blocked_reason=blocked_reason,
                    blocked_evidence=blocked_evidence)
                validations.append(report)
                for item in report.get("per_chat", []):
                    target = item.get("target") or {}
                    checkpoint_mod.append_record(ckpt_path, {
                        "provider_url": url, "candidate_id": cid,
                        "target_token": item.get("chat_url", ""),
                        "chat_url": target.get("href", "") or "",
                        "index": target.get("index", 0),
                        "selector": target.get("selector", "") or "",
                        "verdict": item.get("verdict", ""),
                        "reason": item.get("reason", ""),
                    })
                self._set_status(candidates_done=pos + 1)
        except Exception as exc:
            run_error = str(exc)
            self._log(f"[profiler] validation failed: {exc}")

        if self._cancelled():
            return self._finish_cancelled(validations, matrix, profile,
                                          url, provider_id, n_chats)
        if run_error and not validations:
            validations.append({
                "candidate_id": "?", "per_chat": [],
                "summary": run_mod.verdicts_empty_summary(),
                "skipped": f"error: {run_error}"})
        self._finish_completed(validations, matrix, profile,
                               url, provider_id, n_chats,
                               error=run_error)

    def _store_results(self, validations, matrix, profile,
                       url, provider_id, n_chats):
        out_validations = []
        for validation in validations or []:
            summary = validation.get("summary") if isinstance(validation, dict) else None
            entry = dict(validation) if isinstance(validation, dict) else {}
            entry["rollup"] = verdicts.candidate_verdict(summary)
            out_validations.append(entry)
        try:
            profile_dict = profile_to_dict(profile)
        except Exception:
            profile_dict = {}
        self._results = {
            "url": url,
            "provider": provider_id,
            "n_chats": n_chats,
            "profile": profile_dict,
            "matrix": matrix if isinstance(matrix, dict) else {},
            "validations": out_validations,
        }

    def _finish_completed(self, validations, matrix, profile,
                          url, provider_id, n_chats, error=""):
        self._store_results(validations, matrix, profile,
                            url, provider_id, n_chats)
        with self._lock:
            self._results["error"] = error or ""
            self._status.update(phase=PHASE_COMPLETED, detail="",
                                awaiting_login=False, error=error or "")
        self._log("[profiler] Completed")

    def _finish_cancelled(self, validations=None, matrix=None, profile=None,
                          url="", provider_id="", n_chats=0):
        if validations is not None:
            self._store_results(validations, matrix, profile,
                                url, provider_id, n_chats)
        self._set_status(phase=PHASE_CANCELLED, detail="",
                         awaiting_login=False)
        self._log("[profiler] Cancelled")

    def _finish_failed(self, error):
        self._set_status(phase=PHASE_FAILED, detail="",
                         awaiting_login=False, error=error)
        self._log(f"[profiler] Failed: {error}")

    # -- test seam ---------------------------------------------------------
    def _join(self, timeout=30):
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        return thread
