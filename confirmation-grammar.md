# Confirmation Grammar — Spoken Protocol Spec v2

The safety spine for voice-driven agency. Voice is lossy and ambiguous; this
grammar exists so that no misheard phrase can trigger an irreversible act,
and so every gate-crossing leaves the same auditable trace it would leave
from a keyboard.

v2 changes: revision tokens double as idempotency keys; queue drain gets
forced pacing; driving read-backs shrink to one sentence; second-channel
confirmation is promoted from open item to design option; enforcement layer
made explicit. With the Switchboard ticket backbone as the primary action
layer, the class distribution shifts — most spoken actions are Class R reads
and Class C ticket transitions, and Class X becomes a rare escape hatch.

Design principles:
1. **Confirmation is keyword-bound, never a bare affirmative.** "Yes",
   "yeah", "sure", "do it" are inert everywhere in this grammar.
2. **The confirmation names the operation.** The voice equivalent of typing
   the branch name to delete it.
3. **Read-back precedes every confirmable act** — target, scope, blast
   radius — then an awaiting-confirmation state.
4. **Confirmation keywords are only live inside that state.** No ambient
   armed state.
5. **Gate-crossings are writes.** A confirmed crossing emits a decision-log
   entry carrying a revision token.
6. **Confirmed ≠ executed twice.** The revision token is also the
   idempotency key: execution is applied at-most-once per token. Retries
   from network failures or restarts re-present the token; the executor
   no-ops on a token it has already applied. (Production HITL postmortems
   name double-execution of an approved action as the fastest way to
   destroy trust.)
7. **Enforcement lives in the execution layer, not the prompt.** Operation
   classes are registry data checked in code. A prompt-level "confirm with
   me first" can be compacted out of a long session's context and silently
   lost — this has happened in production (the OpenClaw incident). The
   model's cooperation is welcome; it is not the mechanism.

---

## Operation classes

**Class R — Reversible.** No confirmation, narrated. The bulk of daily use
on the ticket backbone: study-loop digests, ticket reads, decision-corpus
queries, repo summaries, status.

**Class C — Confirmable.** Read-back + keyword confirmation; interruptible
until confirmed, then runs to completion. The working vocabulary: ticket
move/assign/comment, feedback attachment, starting tasks on a surface,
scratch-workspace commits.

**Class G — Gate-crossing.** Class C plus the decision-record write. The
read-back includes the gate's plain-language name and current state; the
confirmation carries the revision-token check; the token is consumed
at-most-once.

**Class X — Destructive/irreversible.** Class C plus: non-interruptible once
confirmed, and a mandatory scope read-back with counts ("delete branch
feature/lockstep-net, 14 commits not on main"). Rare by design under the
ticket backbone: shared-branch pushes, force-push, deletions, out-of-flow
publishing, session kill.

Classification is registry data. An unclassified operation defaults to
Class X.

---

## The exchange, canonically

```
User:   move the cache-concurrency ticket to needs-review
Agent:  Moving cache-concurrency from in-progress to needs-review,
        with your dictated comment attached. Say "confirm move".
        [awaiting: op=move, ttl=15s]
User:   confirm move
Agent:  Done — cache-concurrency is in needs-review.
```

Gate-crossing variant:

```
User:   stamp the phase one gate
Agent:  Gate "voice loop" is at needs-review, revision 7. Stamping
        approved unblocks phase two. Say "confirm gate voice loop".
User:   confirm gate voice loop
Agent:  [decision-log write: gate=voice-loop, approved, token=rev7;
         token unused → applied exactly once]
        Stamped. Voice loop approved at revision 8.
```

Revision moved since read-back:

```
Agent:  Hold on — the gate moved to revision 8 with a new note from
        the linter run. Want the updated read-back?
```

Replay/retry after success: same token re-presented → executor no-ops,
agent reports "already applied at revision 8."

---

## Confirmation keyword forms

- `confirm <operation>` — operation word must match the armed op's label:
  `confirm move`, `confirm send`, `confirm delete branch`.
- `confirm gate <gate name>` — always the plain-language gate name.
- `cancel` / `stop` / `never mind` — universal aborts, live everywhere,
  always fast-path.

Rejected by design: bare `confirm` (re-prompt, no execution); any
affirmative not matching the pattern (treated as ordinary input).

---

## State machine (per confirmable op)

```
        read-back spoken
IDLE ────────────────────► AWAITING ──confirm <op>──► EXECUTING ──► NARRATE ─► IDLE
                             │  │                        │   (token consumed here,
                     ttl 15s │  │ cancel/stop            │    at-most-once)
                             ▼  ▼                        │ Class X: barge-in ignored
                            ABORT (spoken ack)           ▼
                                                     on failure: spoken error;
                                                     retry requires fresh read-back
                                                     and a fresh token
```

Rules:
- **TTL 15 seconds**; expiry gets a spoken "letting that go."
- **One armed op at a time**; a new confirmable request explicitly drops the
  pending one before its own read-back.
- **Retry requires a fresh read-back and fresh token** — never re-execute
  off an old confirmation.
- **Barge-in during read-back** (PTT press) cancels the arm entirely: an
  unheard scope arms nothing.

---

## Mishearing defenses, summarized

PTT removes the open-mic threat surface (no agent-echo path, no ambient
speech during idle), but the defenses stay for dictation mode and any future
open-mic mode:

| Threat | Defense |
|---|---|
| Agent narration resembling a confirmation | Templates never speak a live confirmation phrase verbatim while AWAITING |
| STT confuses similar ops (move vs. remove) | Operation word must match the armed op exactly; near-miss re-prompts |
| Stale intent | 15s TTL |
| Background speech during a held key | Keyword must land inside AWAITING and match the armed op |
| Gate moved under the read-back | Revision token verified at write time; mismatch aborts with fresh read-back offer |
| Retry/replay double-execution | Token consumed at-most-once; replays no-op |

---

## Driving-tier interaction

No operation class is refused while driving. Class G and X follow
**prep-and-queue**:

1. Request accepted; all reversible prep runs (stage, diff, draft, resolve
   revision).
2. Agent narrates **one short sentence** — the in-car cognitive-load
   research says voice interaction is already the heaviest verbal channel,
   so the full scope recitation waits for park. ("Staged the gate stamp for
   voice loop — queued for when you're parked.")
3. Nothing is armed while driving; no AWAITING state exists in motion.
4. On park/charge, or on "what's pending": queued items surface **one at a
   time with forced pacing** — a mandatory beat between items, no
   rapid-fire drain. Each gets a fresh full read-back with the revision
   token re-verified at that moment. Rubber-stamped approvals are worse
   than no gate at all.

Queued items persist for the drive; the 15s TTL applies only once armed.
`cancel <op>` while driving drops a queued item. Class C while driving is a
per-operation registry flag — with the ticket backbone, many transitions are
low-blast-radius and ship default-on.

---

## Second-channel confirmation (design option, was v1 open item)

Cowork remote sessions deliver permission prompts to whichever surface
you're on, including the phone. When available on the relevant plan and
verified against local-MCP constraints, Class X in the **work profile** can
require *both* the spoken keyword and a tap on the phone prompt —
belt-and-suspenders for the regulated side, with zero custom approval
transport to build. Until then, the orchestrator's own queue is the only
channel, and Class X in work profile may simply be desk-only.

---

## Open items for v3

- Numeric disambiguation ("confirm move two") when multiple surfaces have
  same-named pending ops.
- Whether gate-stamp decision-log entries should capture an audio hash of
  the confirmation utterance for the audit trail.
- Confirmation semantics if a queued item's *prep* goes stale (e.g., the
  staged diff no longer applies cleanly at park time) — likely: discard
  prep, re-run, fresh read-back.
