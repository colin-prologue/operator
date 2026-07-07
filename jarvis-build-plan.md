# Voice-First "Jarvis" — Phased Build Plan (v2)

Companion to the Patterns Catalog and the Confirmation Grammar spec (v2).

Positions locked in: cascaded backbone with a router-level seam for a future
S2S lane; explicit sticky profile-split (work = local-first, personal =
cloud); separate orchestrator that drives Claude surfaces over MCP and deep
links; **push-to-talk activation** (wake word dropped); **Switchboard-style
ticket backbone as the primary action layer** with code operations as a
secondary escape hatch; prep-and-queue while driving; keyword-bound
confirmation grammar with revision tokens doubling as idempotency keys.

Changes from v1, in one paragraph: PTT replaces the wake-word gate, which
deletes the always-on detector, most of the echo/self-trigger risk, and the
silence-hallucination exposure (mic only opens under the key). The session
registry generalizes to a **surface registry** spanning chat conversations,
Cowork threads, Code sessions, and tmux sessions, addressed by plain-language
names and reached via the `claude://` / `claude-cli://` deep-link schemes.
The primary tool surface is the Switchboard MCP layer (tickets, queues, gate
stamps, decision corpus); most voice actions become auditable state
transitions rather than code operations. Research findings folded in:
idempotent execution, ducking fallback for any open-mic mode, TTS
cancellation testing, queue-drain pacing, one-sentence driving read-backs.

Each phase ends at a **gate** in your gate-state sense. Crossing a gate is a
deliberate act with a decision record. Nothing in phase N+1 starts until the
phase-N gate stamps.

---

## External dependency: Cowork remote sessions (tracked, not assumed)

Cowork remote sessions (beta) run tasks on Anthropic's servers, persist to
the account, continue with the laptop closed, and are steerable from any
surface — including permission prompts that reach whichever surface you're
on. This is the *target* continuity substrate for car→desk handoff and a
native second confirmation channel.

But it is beta, rolling out by plan tier, chat memory doesn't carry into it,
and plugins with **local MCP servers work through the desktop app only** —
which includes the Switchboard decision-corpus tool. So the plan treats it as
an upgrade path, not a foundation:

- **Working substrate (build now):** tmux persistence + deep links +
  orchestrator-owned approval transport.
- **Upgrade trigger:** remote sessions available on the relevant plan AND
  verified against local-MCP needs. Re-evaluate at Gate 3 and Gate 4;
  decision record either way.

---

## Phase 0 — Bench rig (no voice yet)

**Goal:** router, surface registry, and the Switchboard MCP surface exist and
are testable from a console before any audio touches them.

Deliverables:
- **Intent router**, standalone: priority chain (deterministic fast-path →
  tool router → LLM fallback), driven by text from a console frontend.
  Fast-path table v1: stop, cancel, pause, resume, status, mode switches,
  confirmations, surface addressing.
- **Surface registry** (supersedes v1's session registry): entries are
  `{kind: chat | cowork | code | tmux, plain-language name, address,
  digest}`. Addresses are deep links (`claude://claude.ai/...`,
  `claude://cowork/...`, `claude-cli://open?...`) or tmux session handles.
  Every inbound turn resolves to a surface before routing. Registration is
  explicit and voice-friendly: "call this thread the proxy pilot." The
  registry indexes surfaces the orchestrator opened plus ones registered by
  hand — there is no public list-conversations API, and the design accepts
  that.
- **Deep-link dispatch + send seam**: deep links prefill but do not send, so
  the orchestrator owns the final Enter via OS automation (Accessibility on
  macOS, UI Automation on Windows). Build this as one small, replaceable
  adapter — it is the most brittle seam in the system and should be treated
  as such.
- **Switchboard MCP tool v0 — built in this phase** (it does not exist yet):
  minimal surface of ticket reads, ticket state transitions, gate stamps
  with revision tokens, decision-corpus queries, feedback attachment.
  Git-backed file storage with directory-lane state transitions, per the
  archived Switchboard design. Mounted as the primary tool layer; Claude
  Code mounts as *one tool among several*, not the center. Scope detail in
  the Phase 0 kickoff spec.
- **Profile flag** (work/personal) plumbed end-to-end from day one.

Acceptance:
- Console can register and address two surfaces of different kinds (one tmux
  Code session, one chat via deep link), switch between them by
  plain-language name, issue fast-path commands with zero LLM calls
  (log-verified), move a ticket through a state transition via the
  Switchboard tool, and fall through to LLM routing for everything else.

**Gate 0:** router architecture review. Decision record: fast-path table v1,
surface-addressing grammar, MCP surface, deep-link adapter design.

---

## Phase 1 — Ears and mouth (desk, personal profile, PTT)

**Goal:** a full voice turn against the Phase-0 spine. PTT means no wake
word, no always-on detector, and the mic is physically gated by the key.

Deliverables:
- **Push-to-talk capture**: hold-to-talk as primary; a tap-to-toggle variant
  for long dictation. Key choice must work eyes-free (spacebar at desk; a
  steering-wheel-reachable hardware button is a Phase 4 concern but the
  abstraction lands here).
- Silero VAD retained *inside* the PTT window for end-of-speech trimming and
  the energy-threshold silence guard (a held key over silence must not send
  garbage to STT — the hallucination guard still earns its keep).
- Semantic turn detection is **demoted to optional** under PTT (the key
  release is the turn signal). Keep the seam: if an open-mic conversation
  mode is ever added, it slots back in.
- Two endpoint profiles — **command** (snappy) and **dictation** (patient,
  tap-toggled) — switchable by voice or key gesture.
- Streaming TTS with sentence chunking. **Select the TTS provider partly on
  measured mid-stream cancellation latency** — providers vary; test before
  committing.
- Barge-in, simplified by PTT: pressing the key while TTS plays cancels
  playback (target sub-200ms including an explicit buffer **flush that drops
  queued packets** — jitter buffers hold 200–400ms and must not drain
  naturally), rolls back the turn with an `[Agent Interrupted]` marker.
  Echo/AEC work is deferred: with PTT there is no open mic during playback.
  If an open-mic mode arrives later, start with **partial ducking**
  (10–20dB mic gain cut during agent speech) before reaching for full AEC.
- **Latency dashboard**: per-turn TTFA logged and charted; ~800ms SLO
  tracked from turn one. Gate 3's S2S decision is made on this data.

Acceptance:
- Ten-minute mixed session (commands + questions + one dictated paragraph)
  with zero silence hallucinations, key-press barge-in under 200ms
  flush-to-silence, and median TTFA recorded.

**Gate 1:** voice-loop review. Decision record: PTT ergonomics, endpoint
tuning, TTS provider choice with cancellation numbers, latency baseline.

---

## Phase 2 — Agentic voice on the ticket backbone

**Goal:** voice runs real work, and most of that work is Switchboard state
transitions — study, feedback, ticket updates — with code ops as the
exception.

Deliverables:
- **The study loop**: "what came down" — voice-triggered digests of queue
  changes, repo deltas, and decision-corpus updates since last check,
  narrated in summary form with drill-down on request. This is Class R and
  should feel instant.
- **The feedback skill** (flagship): dictation mode targeting a named ticket
  or review — enter dictation profile, speak, hear a read-back summary,
  attach to the target. Class C throughout.
- **Ticket transition operations** as the primary Class C/G vocabulary:
  move, assign, comment, stamp. Gate stamps carry revision tokens; **the
  revision token doubles as the idempotency key at execution**, so a
  retried approval cannot double-apply (the LiveKit failure mode).
- Confirmation grammar v2 enforced per the companion spec, **at the
  registry/execution layer, never as prompt instruction** — the OpenClaw
  compaction incident is the cautionary case: a prompt-level "confirm with
  me first" got summarized out of context and the agent proceeded without
  it. Classification lives in code.
- **Code operations as escape hatch**: present, classified (mostly Class X),
  reachable, but not optimized for. The router's tool-router tier weights
  the Switchboard surface first.
- Preemptive filler + progress narration for long operations, driven by
  status events.
- Tool-result digests before results re-enter context.

Acceptance:
- By voice alone: run the study loop over a seeded queue, dictate feedback
  onto a ticket, move it through a transition with read-back → keyword
  confirm, and stamp one gate producing a decision-log write whose revision
  token is verified. Negative tests required: a bare "yes" fails to confirm;
  a replayed confirmation against an already-applied revision token is a
  no-op.

**Gate 2:** safety review. Decision record: grammar v2 as-built, registry
inventory with classifications, idempotency verification.

---

## Phase 3 — Work profile (local-first, redaction, audit)

Unchanged in substance from v1:

- Local pipeline for work profile: whisper.cpp STT, local routing models,
  Piper TTS. Cloud reasoning only through an explicit allowlist (empty by
  default). Note the product precedent: Claude Code's own voice dictation
  streams audio to Anthropic's servers and is disabled for
  HIPAA-restricted orgs — the work profile cannot lean on built-in voice
  features and must own its local path.
- Redaction-before-persistence with an audit trail; planted-secret tests.
- Profile switching as a deliberate spoken act, sticky, announced, logged;
  work profile refuses cloud STT/TTS in code.
- Packet-capture verification run kept as an artifact.
- SQLite long-term store with digest compaction, profile-scoped.

**Gate 3:** privacy posture review + scheduled decision points: (a) S2S fast
lane, on three phases of TTFA data; (b) first Cowork-remote re-evaluation
against the upgrade triggers above.

---

## Phase 4 — Mobile and car (degradation ladder, prep-and-queue)

**Goal:** the system survives leaving the desk. PTT hardware becomes the
front door.

Deliverables:
- **Hardware PTT**: a steering-wheel-reachable button (BLE remote or wheel
  control passthrough) mapping to the same hold/tap semantics as the desk
  key. Eyes never leave the road; the button is the entire activation
  surface.
- Graceful-degradation chain, fault-injected: premium TTS → Piper; primary
  LLM → backup; network drop → local command-and-control tier keeping
  stop/status/surface-switch alive.
- **Driving tier: prep-and-queue** (per v1 revision): Class G/X requests
  accepted, all reversible prep runs, confirmation queues rather than arms.
  **Driving read-backs are one short sentence** — the automotive literature
  puts voice interaction at the top of in-car cognitive load, so staging
  summaries stay minimal and the full scope recitation waits for park.
  Ticket-backbone bonus: many transitions are low-blast-radius Class C and
  can be flagged confirmable-while-driving in the registry.
- **Queue drain with forced pacing**: on park, pending items surface one at
  a time with fresh read-backs and a mandatory beat between them — no
  rapid-fire confirm-confirm-confirm. Rubber-stamped approvals are worse
  than no gate.
- Cross-surface continuity test on the working substrate (tmux + deep
  links): start a study-loop + feedback task by voice in the car, finish at
  the desk console against identical state. If Cowork remote has cleared
  its upgrade triggers by now, run the same test on it and compare.

Acceptance:
- Simulated network drop degrades without killing the session; a driving
  gate-crossing preps, queues, and provably does not execute until confirmed
  after parking; queue drain enforces pacing; car→desk handoff works.

**Gate 4:** road-readiness review + second Cowork-remote evaluation.

---

## Phase 5 — Polish and persona (deliberately last)

Acknowledgement style, filler-pool voice consistency, humor/hallucination
disclaimers for low-confidence domains. The wake-word workstream is deleted;
if an always-listening mode is ever wanted, it re-enters here as its own
project with the echo/AEC work it drags along.

---

## Operation inventory (v2, redistributed)

**Class R — the bulk of the day** (no confirmation, narrated):
study-loop digests · "what came down" · repo/delta summaries ·
decision-corpus queries · ticket reads · surface listing/status

**Class C — the working vocabulary** (read-back + keyword confirm):
ticket move/assign/comment · feedback attachment · starting a Code or Cowork
task on a surface · commit in a scratch workspace · sending drafts for
review

**Class G — gate-crossings** (Class C + decision-log write, revision token =
idempotency key):
gate stamps · promoting decisions project→global corpus · approving phased
work

**Class X — rare escape hatch** (Class C + non-interruptible + scoped
read-back with counts):
push to shared branches · force-push · branch/file deletion · send/publish
outside review flow · session kill

**Skills** (deterministic state machines, never free-fired):
gate-crossing · feedback capture · destructive git ops · profile switch ·
surface create/register/kill · dictation delivery

**Fast-path** (no LLM):
stop · cancel · pause · resume · status · "switch to <surface>" ·
"command/dictation mode" · "work/personal mode" (enters profile-switch
skill) · confirmation keywords (live only inside awaiting states)

---

## Standing risks (v2)

- **The deep-link send seam** replaces echo as the top brittleness risk: OS
  automation for the final Enter is version-fragile across app updates.
  Keep it a one-file adapter with a smoke test that runs on every Claude
  Desktop update.
- **Surface registry drift**: deep-link formats and Cowork's session model
  are both young; version the adapter, treat schema skew the way you flagged
  it for Nexus digests.
- **Semantic vocabulary**: jargon-dense transcripts (ADR, CDR, tmux,
  lockstep) still argue for threshold-tuning STT hints on your own audio
  after Phase 1 — Claude Code's dictation gets project/branch names as
  recognition hints, which is the pattern to copy locally.
- **Cowork remote timing**: if it matures faster than expected, resist
  re-platforming mid-phase; the evaluation points are Gates 3 and 4, not
  whenever a changelog drops.
