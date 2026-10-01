"""Provider Profiler (TICKET-002-L) — automatic preset discovery engine.

Pure parts (no Playwright, no App): profile_schema, probes, matrix,
verdicts, checkpoint, reuse. IO parts (injected page, worker thread only):
orchestrator, validation, run (CLI launcher owns the browser).
"""
