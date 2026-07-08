# Workflow — Gate-States and Intents

## Gates

Work proceeds in phases (see [jarvis-build-plan.md](jarvis-build-plan.md)).
Each phase ends at a gate; crossing a gate is a deliberate act with a
decision record:

- Gate state lives in `corpus/gates/<name>.md` — current state plus a
  revision counter.
- A crossing is stamped via the Switchboard tool (`gate_stamp`) with the
  current revision token; the stamp writes a decision-log entry and consumes
  the token (at-most-once, per Constitution article 2).
- Nothing in phase N+1 starts before the phase-N gate stamps.
- Gate 0 decider: Colin.

## Intents (tickets)

Units of work are tickets in `corpus/tickets/`, moving through directory
lanes: `backlog/` → `in-progress/` → `needs-review/` → `done/`. Tickets are
plain-language slugs (`cache-concurrency.md`), never opaque IDs. Every
mutating operation on a ticket produces a git commit whose message carries
the operation, the token, and the profile flag.

## Branch convention

No direct-to-main commits. Work lands on `<type>/v<semver>-<slug>` branches
(e.g. `docs/v0.1.0-stack-adr`) with patch notes in the PR body. Decision
records (`decisions/`, one file per record, ADR/CDR numbered) merge before
or with the code they govern.
