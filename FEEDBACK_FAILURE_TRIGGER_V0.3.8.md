> **V0.4.0 update:** coordinate-level permanent blocking described below is historical. V0.4.0 learns `terrain_type -> impassable`; see `DYNAMIC_TERRAIN_RULES_V0.4.0.md`.

> **V0.3.9 tightening:** this document is superseded by `STRICT_FEEDBACK_EVIDENCE_V0.3.9.md` for evidence correlation. Server-error text alone no longer creates a hard rule; it must be corroborated by `lastRoundRoleActionResults=false` and the exact previous action sent by the agent.

# FortressAgent V0.3.8 — Server Feedback Failure Trigger

## 1. Primary rule

Action failure detection no longer depends on parsing one exact error string.

The authoritative trigger is:

```text
lastRoundRoleActionResults[role_id] == false
```

If this boolean is false, FortressAgent **always** creates an `ActionFailureLesson` for the actual command sent by that role in the previous round (when the previous Experience is available).

Server `errors[].description` and `lastCmdResult` are secondary semantic evidence.

```text
role_action_results=false
        ↓ always
ActionFailureLesson
        ↓
exact-action retry suppression
        ↓
Experience Outcome
        ↓
compact logger: action_execution_failed
        ↓
LLM safety-revision prompt (budget permitting)
```

---

## 2. Why this is required

The real server log can look like:

```text
server_errors = [
  [4, "role 20011 wants MOVE to (23,14), but target is impassable terrain [defenderTaskPoint1]"]
]
```

Notice that the description itself does **not** necessarily contain:

```text
[COMMAND_ERROR]
```

Therefore matching only a literal `[COMMAND_ERROR]` prefix is unsafe.

V0.3.8 parses the semantic payload itself:

```text
role <id> wants MOVE to (<x>,<y>) ... impassable terrain [<terrain>]
```

Both of these are accepted:

```text
[COMMAND_ERROR] role 20011 wants MOVE to (23,14), ...
role 20011 wants MOVE to (23,14), ...
```

---

## 3. Two levels of learning

### A. Boolean failure only

Example:

```json
{
  "lastRoundRoleActionResults": {
    "20011": false
  },
  "errors": []
}
```

This proves:

```text
the exact previous action failed
```

but does **not** prove:

```text
the target cell is permanently impassable
```

So V0.3.8 learns a temporary exact-action ban:

```text
ActionFailureLesson
retry_ban_until_round = current_round + 3
```

This prevents immediate exception loops without incorrectly converting a temporary collision/cooldown/condition failure into a permanent terrain rule.

### B. Parsed impassable-terrain evidence

Example:

```text
role 20011 wants MOVE to (23,14),
but target is impassable terrain [defenderTaskPoint1]
```

This is stronger evidence.

V0.3.8 creates:

```text
CommandErrorLesson
```

and learns:

```text
role-specific MOVE ban: 20011 -> (23,14)
global impassable cell: (23,14)
terrain label: defenderTaskPoint1
```

That coordinate is then rejected by Traversability, candidate generation, LegalActionFilter, pathfinding and FinalResponseValidator.

---

## 4. Compact log trigger

Every `role_action_results=false` generates a compact-log event:

```json
{
  "channel": "trace",
  "record_type": "trace",
  "event": {
    "kind": "action_execution_failed",
    "round_id": 16,
    "data": {
      "role_id": "20011",
      "action_type": "MOVE",
      "action_signature": "...",
      "reason": "role_action_result_false",
      "source": "role_action_result",
      "retry_ban_until_round": 19
    },
    "correlation_id": "r16:attempt:16"
  }
}
```

If `errorCode=4` or a semantic impassable-terrain message is available, `reason` and `raw_feedback` are enriched.

The existing `server_feedback_observed` record remains available and includes:

```text
role_action_results
last_summon_treasure_result
last_command_result
server_errors
```

Therefore one downloaded compact log is sufficient to identify both:

```text
what the server reported
and
what safety lesson the agent learned from it
```

---

## 5. Exact retry suppression

`BasicLegalActionFilter` now checks before action-specific legality:

```text
feedback_memory.is_action_forbidden(action, current_round)
```

So this is not limited to MOVE.

If a previous action such as BUY/BUILD/COLLECT/ATTACK is reported false, the exact same domain action is temporarily removed from the feasible set as well.

For MOVE, parsed impassable-terrain evidence still creates the stronger permanent coordinate ban.

---

## 6. Experience loop

`OutcomeRecord` now records both:

```text
command_error_signatures
and
action_failure_signatures
```

So an execution failure is no longer represented only as:

```text
action_legal = false
```

Replay/Learner/human analysis can recover the exact failed action fingerprint and reason.

---

## 7. LLM/System prompt loop

A new authoritative failed action can trigger one safety-revision prompt (subject to the normal daily LLM budget).

The prompt always contains the doctrine:

```text
A server COMMAND_ERROR or lastRoundRoleActionResults=false is authoritative
negative feedback; do not repeat the same illegal move.
```

If the semantic impassable message was parsed, it additionally contains the exact lesson in normalized form:

```text
[COMMAND_ERROR] role 20011 wants MOVE to (23,14),
but target is impassable terrain [defenderTaskPoint1]
=> NEVER MOVE to (23,14); approach an adjacent walkable interaction cell instead.
```

Deterministic safety memory is effective immediately; LLM re-analysis is advisory and is not required for the ban to work.

---

## 8. Decision hierarchy

```text
role_action_results=false
        │
        ├─ no parseable error text
        │      ↓
        │  temporary exact-action retry ban
        │
        └─ parseable impassable-terrain evidence
               ↓
           permanent MOVE/cell hard constraint
```

This avoids both failure modes:

```text
under-learning:
  repeat an illegal command until elimination

over-learning:
  permanently block a valid action because of a temporary failure
```
