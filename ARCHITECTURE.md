# Architecture — AI Chat Exporter v0.7.1

## Overview

Desktop application that exports AI chat dialogs from five providers (**ChatGPT, Gemini, Claude, Qwen, DeepSeek**) plus **Custom Web** (user-configurable browser-based export) into local Markdown files. No API keys and no cloud services — the app drives a real browser through Chrome DevTools Protocol (CDP) and Playwright, reads the rendered page, and normalizes the content into a unified conversation model.

Custom Web mode also supports an API path for two arbitrary LLM endpoints (Custom 1 / Custom 2), where the app sends prompts and saves responses as Markdown.

```
UI (pywebview) ── window.pywebview.api.* ──> main.py App
                                              │
                     ┌────────────────────────┴──────────────────────────┐
                     ▼                                                    ▼
              _pw_worker (thread)                                 _gw_worker (thread)
              DeepSeekAdapter                                     Gemini / Qwen / ChatGPT / Claude / Custom Web
              own Playwright + CDPContext                           shared CDP browser (own Playwright)
                     │                                                    │
                     ▼                                                    ▼
              DeepSeekExporter                                adapters (list_chats → open_chat → extract_chat)
                     │                                                    │
                     └──────────────┬─────────────────────────────────────┘
                                    ▼
                           conversation/ pipeline
                    IRBuilder → ConversationModel → Enricher → Validator
                                   │
                                   ▼
                           ExportWriter → raw/<service>/*.md
```

## Modules

| Module | Responsibility |
|--------|----------------|
| `ui/` | Desktop UI (HTML/JS/CSS) rendered by pywebview |
| `main.py` | Application orchestration: workers, queues, sync state, cancel |
| `adapters/` | Browser lifecycle (`cdp_manager.py`) + per-provider adapters |
| `adapters/custom_web.py` | Custom Web adapter with SelectorStrategy / ScriptStrategy |
| `adapters/custom.py` | Custom API adapter (send prompt → save response) |
| `conversation/` | Unified data model and enrichment pipeline |
| `exporters/` | Page extraction scripts + markdown writer + attachment capture |
| `core/` | Thread-safe logging (`LogBuffer`), config helpers (`custom_config.py`), preset engine (`preset_engine.py`) |

> **Presets (TICKET-002, released):** `core/preset_engine.py` provides preset validation (`validate_preset`), catalog filtering (`filter_valid_presets`), catalog path (`resolve_catalog_path`) and navigation resolution (`resolve_navigation`). The preset-selection UI (`TICKET-002-E`: select + Apply + Test→check) is finished; built-in verified presets ship in `presets/seed_presets.json` and are copied next to `config.json` on first use (never overwritten). Applicability check: `App.check_custom_web` (counts + verdict + reason) over the shared worker queue. Manual Custom Web configuration and Custom API mode keep working.

> **Provider Profiler (TICKET-002-L engine + TICKET-003 UI):** `core/profiler/` auto-discovers presets for a new provider URL (probes → Provider Profile → Preset Matrix → validation on N chats). Pure parts (`profile_schema/probes/matrix/verdicts/checkpoint/reuse`, no Playwright) + IO layer (`orchestrator/validation`, injected `page`, worker thread only) + CLI launcher (`run.py` owns the Playwright session, single login pause). Research-context order is mandatory: chat-list probe → open first chat (`goto` first, click fallback + `wait_for_function`) → **then** message/user/assistant/title/scroll probes; navigation is never judged from the home page. A product-filter (empty-title links) is reported as `Blocked` with evidence, not a silent `Incompatible`. TICKET-003 adds the UI workflow (Profiler modal: URL → Discovery → Validation → Preset Matrix → Save as Preset), `core/preset_catalog.py` (validate → sanitize/no-secrets → atomic upsert into `custom_presets.json`) and `core/profiler/worker.py` (background runner over the same engine, CDP-attach, login pause, checkpoint in storage). Still no `*_js` synthesis, no writes to `config.json`, no `analysis/*` imports. Notes: verdicts share only the *semantics* of `check_custom_web` (1 page vs N chats have different contracts); output defaults to `profiler_output/` (gitignored). Smoke/launcher: `--cdp <endpoint>` attaches to a trusted running Chrome instead of `launch` (attached browser is never closed, only our page). Binding verdict `wrong_target` is graded: `Incompatible` = no switch proven, `Partial` = switched but this target unconfirmed.

## Runtime model

- **CDPManager** (`adapters/cdp_manager.py`) owns the Chrome process only — no Playwright, no pages. It resolves Chrome in order **bundled → system → `RuntimeError`**, launches it with `--remote-debugging-port=9222` and a persistent profile (`~/.ai_pipeline/chrome_gemini`), so logins survive restarts.
- **Two worker threads**: `_pw_worker` runs DeepSeek with its own Playwright instance and a `CDPContext` wrapper (single window); `_gw_worker` runs Gemini, Qwen, ChatGPT, Claude, and Custom Web against the shared CDP browser.
- Each provider has its own lock (`_locks[provider]`, non-blocking) — exporting one provider never blocks another.
- Cancellation is a single global flag (`_cancel_flag` + `_cancel_version` token) applied in three layers: cooperative `_check_cancel()` in loops → `_soft_stop()` (`window.stop()` on all pages) → versioned `pw_call()` wrapper for Playwright I/O.
- **Custom Web lifecycle**: connect/disconnect/scan commands go through `_gw_queue` to run in `_gw_worker` (Playwright thread affinity). `_custom1_connected` / `_custom2_connected` flags track connection state; `_is_provider_connected` reads flags, not `page.evaluate`. Export via `_export_provider` handles both URL strings and `{url, _index}` dicts to preserve sidebar position for non-href elements.

## Provider integration

| Provider | Adapter | Navigation & extraction |
|----------|---------|--------------------------|
| ChatGPT | `ChatGPTAdapter` | Adapter path: `list_chats()` → `open_chat()` → `extract_chat()` (sidebar scan + click-through). Extraction pipeline: API → `NEXT_DATA` → DOM |
| Gemini | `GeminiAdapter` | Sidebar link click (no deep-link hydration in the SPA). Extraction: RPC (`/_/Batchexecute`) first, DOM scroll-loop as fallback |
| Claude | `ClaudeAdapter` | Adapter path: sidebar scan + click-through. DOM extraction with a fallback pass when assistant messages lack marker attributes |
| Qwen | `QwenAdapter` | Sidebar DOM FSM (click → wait for messages in URL). Extraction: DOM scroll-loop with CDP `DOMSnapshot` fallback |
| DeepSeek | `DeepSeekAdapter` | Own worker thread; `DeepSeekExporter` scroll engine over the conversation page |
| Custom Web | `CustomWebAdapter` | User-configurable: `SelectorStrategy` (CSS selectors) or `ScriptStrategy` (custom JS). Shared CDP browser. Connect/disconnect/scan lifecycle. |
| Custom 1/2 (API) | `CustomAdapter` | Send prompt via HTTP (OpenAI or Anthropic protocol), save response as Markdown. No browser required. |

ChatGPT and Claude connect through the shared CDP context (`_cdp_browser().contexts[0]`); Gemini, Qwen, and Custom Web share the same browser context. A `_cdp_lock` protects browser-level operations (`new_page` + `goto`) only — not the whole export.

## Conversation pipeline (`conversation/`)

- **IRBuilder** (`irbuilder.py`) — converts raw provider output into a unified `ConversationModel`.
- **ConversationModel** (`models.py`) — the core representation: messages, attachment nodes, validation results.
- **Enricher** (`enrichment.py`) — attaches runtime data and CDP-captured assets (`CapturedAsset`) and blobs to messages. Attachments that cannot be fetched (CDN/blob) are marked as `partial`; the chat is still exported.
- **Serializer** (`serializer.py`) / **Validator** (`validator.py`) — tree conversion (`tree_to_dict` / `dict_to_tree`) and consistency checks.

## Export path (`exporters/writer.py`)

- **ExportWriter** writes to `raw/<service>/{service}_{stable_id[:8]}_{hash6}.md`.
- `stable_id` chain: `data["chat_id"]` → URL last segment → `sha1(title|source)[:12]`.
- **Atomic write**: `.md.tmp` → `.replace()` (NTFS/ext4). Existing files are never overwritten.
- **Dedup**: a hash comment inside each file (`<!-- hash: … title: … chat_order: … -->`).

```markdown
<!-- hash: e7f89a title: chat title chat_order: 0 -->

#### 👤 Вы (2024-01-15 14:30)
user message

#### 🤖 AI
assistant message
```

## UI bridge (pywebview)

JavaScript calls `window.pywebview.api.*`; the backend always raises `RuntimeError` on failure (never returns an error string).

| Method | Purpose |
|--------|---------|
| `launch_chrome()` / `close_chrome()` | Start/stop the CDP Chrome instance |
| `connect_gemini()` / `connect_qwen()` / `connect_chatgpt()` / `connect_claude()` | Open the provider page in the shared CDP browser |
| `add_account(url)` | DeepSeek login / chat URL registration |
| `sync_gemini("[]")` / `sync_qwen("[]")` / … | Enqueue a batch export for one provider |
| `sync_all()` | One thread per connected provider, joined after completion |
| `cancel_all()` | Set the cancel flag + bump the cancel version |
| `get_providers_status()` / `get_cdp_status()` | Provider connection flags / CDP endpoint availability |
| `get_custom_config(slot)` / `set_custom_config(slot, json)` | Read/write a Custom slot's config (API or Web mode) |
| `test_custom(slot, json)` / `generate_custom(slot, prompt)` | Verify an API endpoint and generate + save a response |
| `connect_custom_web(slot, url)` / `disconnect_custom_web(slot)` | Open/close a Custom Web slot's browser page |
| `scan_custom_web(slot)` / `export_custom_web(slot, "[]")` | Scan and export chats for a Custom Web slot |
| `get_version()` / `check_update()` | Current `APP_VERSION` / compare with the latest GitHub release |
| `get_output_dir()` / `set_output_dir(path)` / `open_output_dir()` | Read/select/open the export folder |
| `get_log()` / `save_log()` | Read the UI log buffer / dump it to a debug file |

Sync state per provider (`idle` → `running` → `done` / `failed`) is pushed to the UI as `setProviderSync(provider, status)`.

`bind_preset(slot, preset_id)` stores the in-memory slot→preset binding, exposed through the bridge and called from the UI Apply flow (`ui/app.js`); navigation resolves from the bound preset (default `goto`).

## Error handling

| Layer | Success | Error |
|-------|---------|-------|
| Backend | `return value` / `dict` | `raise RuntimeError(...)` |
| API bridge | value via pywebview | exception → Promise rejection |
| UI | `.then(resp)` | `.catch(err)` |

## Bundled runtime

Release builds are PyInstaller `onedir` packages that ship their own Chromium:
- `PLAYWRIGHT_BROWSERS_PATH` is pointed at `<exe_dir>/ms-playwright` before the first `sync_playwright().start()`.
- Chrome resolution in `CDPManager`: bundled → system → `RuntimeError`.
- No system Python or Chrome is required at runtime.

## File structure

```
├── main.py                      # Entry point (pywebview UI + 2 workers)
├── adapters/
│   ├── base.py                  # BaseAdapter ABC
│   ├── cdp_manager.py           # CDPManager (browser lifecycle) + CDPContext
│   ├── chatgpt.py               # ChatGPTAdapter
│   ├── claude.py                # ClaudeAdapter
│   ├── qwen.py                  # QwenAdapter
│   ├── gemini.py                # GeminiAdapter
│   ├── deepseek.py              # DeepSeekAdapter
│   ├── custom.py                # CustomAdapter (API mode: send prompt → save)
│   └── custom_web.py            # CustomWebAdapter + SelectorStrategy + ScriptStrategy
├── conversation/
│   ├── models.py                # ConversationModel (core)
│   ├── irbuilder.py             # IRBuilder: adapter → ConversationModel
│   ├── adapters.py              # ChatGPT __NEXT_DATA__ → ConversationModel
│   ├── enrichment.py            # Enricher: CDP assets + runtime + blobs
│   ├── serializer.py            # serialization
│   └── validator.py             # validation
├── exporters/
│   ├── writer.py                # ExportWriter (atomic write, dedup, timestamps)
│   ├── gemini_extract.py        # Gemini DOM extraction
│   ├── chatgpt_extract.py       # ChatGPT DOM extraction
│   ├── claude_extract.py        # Claude DOM extraction
│   ├── qwen_extract.py          # Qwen DOM extraction
│   ├── deepseek.py              # DeepSeekExporter
│   └── attachment_capture.py    # CDP attachment capture
├── core/
│   ├── logger.py                # LogBuffer (thread-safe)
│   ├── custom_config.py         # DEFAULT_SLOT, load/save custom config
│   └── preset_engine.py         # preset validation / catalog path / navigation (UI wiring in progress)
├── ui/
│   ├── app.html                 # UI layout (tabs-bar + tab-panels, mode toggle, web fields)
│   ├── app.js                   # UI logic + pywebview bridge + tab switching/state management
│   ├── app.css                  # Styles + tabs + connected/syncing states + splash
│   └── icon.ico                 # Window icon
└── raw/                         # Output .md files (gitignored)
```

## Dependencies

- Python 3.10+
- `pywebview>=4.0` — native desktop window with a web UI
- `playwright>=1.40` — browser automation and CDP connection
