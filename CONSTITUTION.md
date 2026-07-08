# Operator Constitution

Guardrails for every phase. Amendments may add or strengthen articles; they
never dilute. Every article is enforced in code or CI, not in prompts —
prose never binds.

## Articles

1. **Operation classes are registry data enforced in the execution layer;
   never prompt-level.** Unclassified operations default to Class X.
   (Cautionary case: the OpenClaw compaction incident — a prompt-level
   "confirm with me first" was summarized out of a long session's context
   and silently lost.)

2. **Revision tokens are idempotency keys; execution is at-most-once per
   token.** A replayed token is a verified no-op, never a second execution.

3. **No capability is added without a class assignment.**

4. **The profile flag (work/personal) is present on every log line and every
   persisted record from the first commit.**

5. **The desktop adapter stays one file with a smoke test; nothing else may
   import OS-automation APIs.**

## Amendment rule

Amendments land as decision records in `decisions/`. Weakening or removing
an article requires an explicit gate-stamped decision by Colin.
