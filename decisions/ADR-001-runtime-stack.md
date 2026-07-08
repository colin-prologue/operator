# ADR-001: Runtime stack — Python 3.12+ / asyncio

**Status:** Accepted (PR #1 merged 2026-07-08)
**Date:** 2026-07-07
**Deciders:** Colin

## Context

The Phase 0 kickoff spec makes the runtime choice the first deliverable, ahead
of any router code. The process being chosen must:

- **Serve MCP** (Switchboard tool v0) and **consume MCP** (driving Claude
  surfaces) from day one.
- Host, in Phase 1, the voice loop *in the same process*: PTT capture →
  Silero VAD → streaming STT → sentence-chunked streaming TTS, with <200ms
  barge-in cancellation.
- Run a priority-chain router (fast-path → tool router → LLM fallback) with
  sub-10ms fast-path dispatch as a single long-lived process.
- Drive the deep-link desktop adapter (fire `claude://` URLs; synthesize the
  final Enter via macOS Accessibility).
- Support, in Phase 3, a local-first work profile: whisper.cpp STT, Piper
  TTS, local routing models.

Criteria, in strict priority order (from the spec):

1. MCP maturity (serving **and** consuming)
2. Streaming-audio path for Phase 1
3. Single long-lived process, sub-10ms fast-path dispatch
4. macOS-first, Windows-eventually
5. Boring beats novel; fewer moving parts breaks ties

**Method.** Five candidate stacks were researched by independent agents with
web-verified July 2026 sources; three cross-cutting sweeps covered the audio
framework landscape, the macOS automation seam, and the Phase 3 local
pipeline. A three-lens judge panel (strict-criteria, operational-boring,
forward-risk) ranked the candidates **unanimously**; three adversarial
refuters then attacked the winner and **none flipped it** (0/3). A Decision
Oracle query for prior cross-project precedent returned empty — this is a
fresh decision.

## Options Considered

Scores are 0–10 per criterion, from the independent research pass:

| Stack | 1. MCP | 2. Audio | 3. Process | 4. Platform | 5. Boring |
|---|---|---|---|---|---|
| **Python 3.12+ / asyncio** | 9 | 9 | 8 | 8 | 9 |
| TypeScript / Node | 9 | 6 | 9 | 8 | 6 |
| Go 1.24+ | 9 | 4 | 9 | 7 | 5 |
| Rust / tokio | 7 | 4 | 10 | 7 | 2 |
| Swift 6 (macOS) | 4 | 6 | 9 | 6 | 3 |

### Option A: Python 3.12+ / asyncio

Official Anthropic-maintained `mcp` SDK (v1.28.1 stable, server + client over
stdio/SSE/streamable-HTTP); uv packaging; Pipecat or LiveKit Agents for the
Phase 1 audio layer; pywhispercpp + Piper + official silero-vad for Phase 3;
PyObjC for the desktop adapter.

**Pros:** Only runtime where both named audio frameworks are native and embed
in the router's existing asyncio loop (Pipecat's runner is an awaitable with a
documented long-lived-host mode — no re-hosting). Tier 1 reference-class MCP
SDK covering both roles. Maintained first-party or reference implementations
at every Phase 3 stage. Zero new runtimes added to the estate — Switchboard
(shipped Python/asyncio orchestrator, 120 tests) and Hindsight are already
Python, so router patterns port directly. Strongest Windows UIA story
(pywinauto) for later. A proven fully-local macOS Pipecat agent exists at
<800ms voice-to-voice on M-series.

**Cons:** GIL/GC tail latency shares the interpreter with the barge-in budget
(measured ~100ms p99.9 under adversarial load in one process); the escape
hatch (free-threaded 3.14) is not production-clean for the extension stack.
MCP Python SDK v2 lands ~2026-07-27 with a breaking rename (FastMCP →
MCPServer) — guaranteed near-term migration. Maintained Piper is now GPL-3.0.
Pipecat's local/offline path is a small corner of Daily's cloud business.
Distribution of a Python daemon with native deps is clunky if Operator ever
ships to others.

### Option B: TypeScript / Node

Official `@modelcontextprotocol` SDK — the flagship MCP implementation, with
the fullest documented client coverage.

**Pros:** Arguably the strongest single MCP SDK; event loop trivially meets
the fast-path budget; developer is fluent.
**Cons:** Loses decisively on criterion 2: Pipecat is Python-only, and
LiveKit's agents-js is the trailing second-class port whose production
architecture assumes a LiveKit media server — heavyweight and off-label for a
single-user local PTT loop. Native mic capture is prototype-grade
(naudiodon). Phase 3 bindings are community-grade with a single-vendor
chokepoint (sherpa-onnx). Ecosystem fork: Switchboard and Hindsight are
Python, so TS means a rewrite or a permanent two-runtime estate — a direct
violation of criterion 5.

### Option C: Go 1.24+

Official `modelcontextprotocol/go-sdk` (Google-co-maintained, v1-stable,
bidirectional).

**Pros:** Excellent MCP SDK; best-in-class process model (goroutines, context
cancellation, single binary).
**Cons:** No voice-agent framework exists in Go — criterion 2 becomes "build
a framework," not "integrate one": bespoke VAD orchestration, hand-rolled
streaming TTS WebSocket clients (no official ElevenLabs/Cartesia Go SDKs),
semi-abandoned whisper.cpp bindings, no Piper binding. The cgo tax (PortAudio,
ONNX, whisper.cpp) erases the single-static-binary advantage by Phase 1. Zero
prior-art leverage.

### Option D: Rust / tokio

Official `rmcp` SDK (v2.1.0).

**Pros:** Ceiling-free process model — no GIL, no GC, sub-10ms with three
orders of magnitude to spare.
**Cons:** Entire Phase 1 pipeline hand-assembled from pre-1.0, mostly
single-maintainer crates (community Deepgram SDK 0.10, piper-rs 0.1.6, ort
still at 2.0 RC); rmcp shipped two breaking majors in ten days of late June
2026; developer not fluent in Rust; buys latency headroom the spec doesn't
need at the steepest velocity cost on the table — a near-total failure of
criterion 5.

### Option E: Swift 6 (macOS-native)

Official MCP Swift SDK (v0.12.1).

**Pros:** Best native macOS story (AVFoundation, AXUIElement, ANE-accelerated
local audio via FluidAudio/WhisperKit); compiled single binary.
**Cons:** Disqualified on criterion 1: the MCP Swift SDK is officially Tier 3
"experimental" — pre-1.0, bus-factor-one, no commits in ten weeks, no
conformance or critical-bug commitments for the protocol the entire product
hangs on. Windows-eventually means rewriting the whole differentiating layer
(all Apple-only APIs). New language for the developer.

## Trade-off Analysis

**Criterion 1 produces a three-way tie** — Python, TypeScript, and Go all
have official, spec-current, bidirectional Tier-1-class SDKs, and all three
face the same 2026-07-28 spec/v2 churn, so it differentiates nothing among
them. Rust drops (API churn, less battle-tested client); Swift is eliminated.

**Criterion 2 decides the ADR, and it is not close.** Python is the only
runtime where both named frameworks are native, where the pipeline embeds in
the router's existing event loop without re-hosting, where barge-in is a
built-in feature rather than a hand-rolled cancellation problem, and where
two maintained frameworks (Pipecat + LiveKit Agents) provide redundancy no
other stack has. TypeScript's one framework is a trailing port with a
media-server assumption; Go, Rust, and Swift convert criterion 2 into "build
and own a voice framework forever."

**Criterion 3 is met by every candidate** for deterministic dict/regex
dispatch (microseconds). Python is genuinely weakest on tail latency — this
is the one real engineering risk of the decision and is handled via the
mitigation ladder below, with the Phase 1 latency dashboard as the tripwire.

**Criterion 4 mildly favors interpreted runtimes**, counterintuitively: the
macOS Accessibility TCC grant binds to the signed interpreter binary and
survives every code edit, whereas a recompiled native binary can invalidate
its grant without a codesigning pipeline. Deep links are portable everywhere;
Python has the strongest Windows UIA library for later.

**Criterion 5 seals it**: Python adds zero new runtimes to an estate that
already includes Switchboard (Python/asyncio, 120 tests) and Hindsight.

## Decision

**Python 3.12+, asyncio, one long-lived process**, specifically:

- **MCP:** official `mcp` SDK, pinned to v1.28.x for Phase 0. The v2
  migration (stable targeted 2026-07-27; FastMCP → MCPServer) is scheduled,
  not incidental: revisit at Gate 0 review. Keep the Switchboard tool surface
  small (the spec'd 7 tools) so migration cost stays bounded.
- **Packaging:** uv workspace across the `packages/*` monorepo layout.
- **Phase 1 audio (deferred, but shapes the choice):** Pipecat embedded in
  the router's event loop; LiveKit Agents is the named fallback. Phase 0
  carries no audio dependencies.
- **Phase 3 local:** pywhispercpp (whisper.cpp), Piper via subprocess/HTTP —
  process isolation keeps the GPL-3.0 boundary outside the router — official
  silero-vad, llama-server over HTTP.
- **Desktop adapter:** in-process PyObjC using CGEventPost for the final
  Enter (Accessibility grant only; avoid osascript's dual Automation +
  Accessibility grants and per-keypress subprocess). When the router
  graduates to a LaunchAgent, pin the interpreter path so the TCC grant stays
  attached to a stable signed binary.

### GIL/GC tail-latency mitigation ladder

1. Keep pure-Python hot loops off the audio path; inference stays in
   GIL-releasing native extensions (verified for pywhispercpp and
   onnxruntime — any replacement binding must be audited for the same
   property).
2. The Phase 1 latency dashboard measures actual tails against the 200ms
   barge-in and ~800ms TTFA budgets from turn one.
3. Escape hatch, in order: split audio into a subprocess (router stays put);
   only then reconsider the runtime.
4. Free-threaded Python 3.14 is **not** assumed — its extension ecosystem is
   not yet production-clean.

## Consequences

- **Easier:** router patterns port from Switchboard; one debugging surface,
  one packaging tool; both audio frameworks and every Phase 3 stage have
  maintained Python paths; failure modes are shared with a large ecosystem
  rather than bespoke.
- **Harder:** tail-latency discipline is now a standing engineering
  constraint on everything that runs in the router process; the MCP v2
  migration is a known, dated tax; native-dep packaging is a liability if
  Operator is ever distributed.
- **To revisit:** see triggers below; each is a condition under which this
  ADR should be re-run, not silently endured.

## Revisit triggers

Distilled from the adversarial refutation pass — the recommendation stands
today, but flips if any of these become true:

1. **Measured tails breach budget:** GIL/GC latency violates the <200ms
   barge-in or fast-path budget under real load and a subprocess split
   doesn't fix it → re-run for a compiled runtime.
2. **Pipecat's local path rots:** LocalAudioTransport / local VAD-STT-TTS
   services are deprecated or unmaintained AND LiveKit's local console mode
   stays dev-only → Python's criterion-2 advantage collapses to a bare
   pipeline; re-run with Go/Rust bare pipelines back on the table.
3. **Concurrent voice sessions in one process** become a requirement —
   Pipecat mandates process-per-session; the one-process premise collapses.
4. **Distribution:** Operator becomes a shipped product (signed/notarized
   installers) → packaging TCO favors a compiled shell.
5. **Windows becomes near-term** *including the voice loop* (not just the
   text router) → Pipecat's un-championed Windows story forces per-platform
   forks; re-score criterion 4.
6. **MCP Python SDK v2 migration goes badly** (sustained instability past
   Q3 2026 while the Go/TS SDKs stay calm) → sustained churn asymmetry on
   the topmost criterion justifies revisiting.

## Action items

1. [ ] Scaffold the monorepo as a uv workspace with all five packages under
   `packages/`: `packages/router`, `packages/registry`,
   `packages/switchboard-mcp`, `packages/desktop-adapter`,
   `packages/console` (per the kickoff spec's layout).
2. [ ] Pin `mcp` to v1.28.x; add a dated re-check of v2 stability to the
   Gate 0 review agenda.
3. [ ] Desktop adapter: PyObjC + CGEventPost, one file, smoke test per the
   kickoff spec.
4. [ ] Record TTFA/latency instrumentation as a router requirement now, so
   the Phase 1 dashboard has hooks to attach to.

## Key evidence

- Official MCP Python SDK v1.28.1 stable (June 2026), server + client,
  Production/Stable — <https://pypi.org/project/mcp/>; v2.0.0b1 implements
  the 2026-07-28 spec, renames FastMCP → MCPServer, stable targeted
  2026-07-27 — <https://github.com/modelcontextprotocol/python-sdk/releases>
- Pipecat v1.5.0 (2026-07-04), local mic/speaker pipeline with no media
  server, built-in Silero VAD, first-class barge-in; runner embeds as an
  awaitable with a documented long-lived-host mode —
  <https://github.com/pipecat-ai/pipecat>
- LiveKit Agents v1.6.4 (June 2026), built-in interruption handling, native
  MCP tool support — <https://github.com/livekit/agents>
- Fully local Pipecat voice agent on M-series macOS at <800ms
  voice-to-voice — <https://github.com/kwindla/macos-local-voice-agents>
- pywhispercpp v1.5.0 (May 2026) — <https://github.com/absadiki/pywhispercpp>;
  whisper.cpp v1.9.1 ships built-in Silero VAD and a realtime stream example
- Piper: MIT original archived Oct 2025; maintained fork is GPL-3.0
  OHF-Voice/piper1-gpl v1.4.2 with the only first-class (Python) API
- MCP Swift SDK officially Tier 3 "experimental", pre-1.0, no commits
  2026-04-29 → 2026-07-07; rmcp shipped breaking v2.0.0 → v2.1.0 within ten
  days (late June 2026)
- macOS TCC: Accessibility grants bind to the signed responsible binary;
  CGEventPost needs Accessibility only, osascript needs Automation +
  Accessibility
