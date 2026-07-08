# LOG-001: Phase 0 bench rig — as-built deltas

**Date:** 2026-07-08
**Scope:** Deltas between the Phase 0 kickoff spec / implementation plan and
the code as merged. Required by Gate 0 ("the stack ADR plus this spec's
as-built deltas are in the decision log").

## Behavioral deltas (strengthen the spec, found in review)

1. **Registry rename guards.** `SurfaceRegistry.rename` refuses renaming
   onto an existing different surface (ValueError) and treats self-rename
   as a safe no-op. The plan's reference code silently destroyed data in
   both cases.
2. **Announced pending-op drops.** The grammar spec's "a new confirmable
   request explicitly drops the pending one" is made literal:
   `ConfirmationMachine.arm` prefixes the new read-back with
   "Dropping the pending <label>."
3. **Exception-safe turn logging.** `Router.handle` logs every turn via
   try/finally — dispatch errors log `outcome="error:<ExcName>"` with
   tier 0, then re-raise (constitution art. 4: every turn logs).
4. **Token shape validation.** `CorpusStore._apply_token` requires
   `^rev\d+$` before any comparison; previously the `"-"` frontmatter
   sentinel matched a caller-supplied `"-"` token and silently reported
   `already_applied`.
5. **Structured MCP errors.** All seven switchboard tools return JSON for
   error cases: `{"status": "stale_token", "current_revision": N}` and
   `{"status": "error", "message": ...}` (unknown names/lanes), never raw
   MCP tool-execution errors.
6. **ClaudeCLI never raises.** The tier-3 fallback (`claude -p <prompt>
   --output-format text` subprocess, subscription tokens — no API-key
   plumbing) returns a clear error string on non-zero exit *and* on a
   missing binary (FileNotFoundError guard).

## Structural deltas

7. **Import naming.** Packages import as `operator_*` — a bare `operator`
   package would shadow the Python stdlib module.
8. **Dynamic confirmation labels.** `CatalogueEntry.label_for` builds
   per-target labels (`confirm gate <name>`, `confirm kill <name>`) per
   grammar principle 2.
9. **Acceptance fixture task-shape.** pytest-asyncio runs async-generator
   fixture setup/teardown in separate tasks, which anyio's cancel scopes
   reject; the bench fixture therefore runs the MCP stdio lifecycle in one
   long-lived background task with an Event handshake, made fail-loud
   (30s setup timeout, task-exception re-raise, 15s teardown bound).
10. **Root-anchored runtime ignores.** `/logs/` and `/registry/` in
    .gitignore — unanchored `registry/` would silently ignore future files
    under `packages/registry/`.
11. **Record formats.** Tickets/gates are markdown with `---` frontmatter
    carrying `name`, `revision`, `last_applied_token`, `profile`; gate
    stamps write `decisions/GATE-<name>-rev<N>.md` (one file per record);
    every mutating call commits as
    `switchboard: <op> <target> token=<token|-> profile=<profile>`.

## Known warts (accepted for Phase 0, revisit in Phase 1)

12. **MCP server log leakage.** The switchboard server's stderr
    ("Processing request of type …") interleaves with console output in
    the live REPL. Cosmetic; silence via logging config in Phase 1.
13. **Reactive TTL expiry.** Confirmation TTL expiry surfaces on the next
    input, not proactively — fine for a text console; spoken "letting that
    go" needs a timer in Phase 1.
14. **Error taxonomy.** The server's `_guarded` catch conflates internal
    bugs with not-found (`{"status": "error"}` for both); a router-level
    error taxonomy is deferred.

## Outstanding manual item

- **Goal condition 6** (desktop adapter smoke against real Claude
  Desktop): deliberately not run by the agent session — synthesizing an
  Enter keypress lands on whatever window has focus. Run manually:
  `uv run python packages/desktop-adapter/smoke.py` (requires the
  Accessibility grant), and re-run after every Claude Desktop update.
