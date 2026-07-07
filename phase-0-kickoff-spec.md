# Phase 0 Kickoff Spec — Bench Rig

The handoff document for the code session. Governs Phase 0 of the Jarvis
build plan (v2); read alongside the Confirmation Grammar spec (v2). Phase 0
is voiceless: it produces the router, the surface registry, the Switchboard
MCP tool v0, and the deep-link adapter, all drivable from a console.

---

## First task: the stack ADR

The runtime is deliberately undecided. The code session's first deliverable
is an ADR choosing it — evaluated against these criteria, in priority order:

1. **MCP maturity**: first-class libraries for both *serving* MCP (the
   Switchboard tool, the outbound orchestrator surface) and *consuming* it.
2. **Streaming-audio path for Phase 1**: the router process will later host
   PTT capture → streaming STT → sentence-chunked TTS. The stack must have a
   credible streaming story (Pipecat and LiveKit Agents are the known
   Python-centric candidates; a bare implementation is acceptable if the
   audio layer can be bolted on without re-hosting the router).
3. **Single long-lived process** friendly to a priority-chain router with
   sub-10ms fast-path dispatch.
4. **macOS-first, Windows-eventually** (home machine hosts v1; the L&W
   Windows machine is a later concern).
5. Boring beats novel. If two options tie, take the one with fewer moving
   parts.

The ADR follows the house format (context, options with trade-offs,
decision, consequences) and lands in the decision log before any router
code is written.

## Second task: repo scaffold

Monorepo, created before feature work:

```
jarvis/
  CONSTITUTION.md          # guardrails (seed below)
  WORKFLOW.md              # gate-states + intents convention
  decisions/               # ADR/CDR log, one file per record
  corpus/                  # Switchboard tool's git-backed store
    tickets/
      backlog/  in-progress/  needs-review/  done/    # directory lanes
    gates/                 # one file per gate: state + revision counter
  packages/
    router/                # intent router + fast-path table
    registry/              # surface registry
    switchboard-mcp/       # MCP tool v0
    desktop-adapter/       # deep-link dispatch + send seam (one file)
    console/               # text frontend
```

Constitution seed (expand in-session, do not dilute):
- Operation classes are registry data enforced in the execution layer;
  never prompt-level. Unclassified ops default to Class X.
- Revision tokens are idempotency keys; execution is at-most-once per token.
- No capability is added without a class assignment.
- The profile flag (work/personal) is present on every log line and every
  persisted record from the first commit.
- The desktop adapter stays one file with a smoke test; nothing else may
  import OS-automation APIs.

## Scope: Switchboard MCP tool v0

Build, don't mount — the tool does not exist yet. Minimal surface, exposed
over MCP:

| Tool | Behavior | Class |
|---|---|---|
| `ticket_list(lane?)` | list tickets, optionally by lane | R |
| `ticket_read(name)` | full ticket by plain-language name | R |
| `ticket_transition(name, to_lane, token)` | move file between lane dirs; token = current revision; at-most-once | C |
| `ticket_comment(name, body)` | append feedback block | C |
| `gate_read(name)` | gate state + current revision | R |
| `gate_stamp(name, state, token)` | write decision-log entry; verify token against current revision; consume token | G |
| `corpus_query(text)` | search decisions/ and corpus/ | R |

Storage is git-backed files with directory-lane transitions (the archived
Switchboard design). Every mutating call produces a commit whose message
carries the operation, the token, and the profile flag. Names are
plain-language slugs ("cache-concurrency"), never opaque IDs.

Non-goals for v0: multi-user, remote hosting, Nexus-style cross-project
aggregation, schema migration. Single local corpus, single user.

## Contract: surface registry

```json
{
  "name": "proxy-pilot",
  "kind": "cowork | chat | code | tmux",
  "address": "claude://... | claude-cli://... | tmux:<session>",
  "digest": "one-line human summary",
  "registered_at": "ISO 8601",
  "profile": "work | personal"
}
```

Stored as one JSON file per surface under `registry/surfaces/`. Operations:
register, rename, list, resolve(name) → address, kill (Class X). Resolution
is exact-match first, then fuzzy over names with a spoken-style
disambiguation hook (returns candidates rather than guessing when >1 match).

## Contract: router

- Priority chain, evaluated top-to-bottom, first match returns:
  1. fast-path table (exact + small synonym set; no LLM)
  2. tool router (keyword selection over the registered tool catalogue)
  3. LLM fallback
- Fast-path v1: stop, cancel, pause, resume, status, "switch to <surface>",
  mode switches, confirmation keywords (live only when the grammar's state
  machine says AWAITING).
- Every turn logs: resolved surface, matched tier, latency, profile.
- The confirmation state machine from the grammar spec lives in the router
  package and owns the AWAITING lifecycle; the MCP tool only verifies and
  consumes tokens.

## Contract: desktop adapter

One file. Two functions: `open(address)` (fires the deep link via the OS
URL handler) and `send()` (issues the final Enter via macOS Accessibility).
A smoke test script exercises both against Claude Desktop and is run
manually after every Desktop update. Nothing else in the repo touches
OS-automation APIs.

## Acceptance criteria — as goal conditions

Written for `/goal`; each independently verifiable:

1. `console` can register two surfaces of different kinds (one tmux session,
   one chat deep link) and `resolve` each by plain-language name.
2. "switch to <name>" routes via the fast-path tier with zero LLM calls,
   proven by the turn log.
3. A ticket seeded in `backlog/` can be listed, read, commented, and
   transitioned to `needs-review/` through the MCP tool, producing git
   commits with operation + token + profile in each message.
4. `gate_stamp` with the current revision token succeeds exactly once;
   re-invoking with the same token is a verified no-op; invoking with a
   stale token fails with the current revision in the error.
5. A request matching no fast-path entry reaches the LLM fallback tier and
   the turn log shows tier 3.
6. `desktop-adapter` smoke test opens a prefilled chat via `claude://` and
   sends it on macOS.
7. Every log line and every persisted record carries the profile flag.
8. An operation invoked without a class assignment is refused as Class X
   behavior (confirmation demanded), proven by test.

## Out of scope for Phase 0

Audio of any kind · the confirmation grammar's spoken layer (the state
machine is built and console-driven; TTS read-backs are Phase 1) · Windows
adapter · Cowork remote integration · queue/driving tier · redaction layer.

## Gate 0

Stamps when all eight goal conditions pass and the stack ADR plus this
spec's as-built deltas are in the decision log. Deciders: Colin.
