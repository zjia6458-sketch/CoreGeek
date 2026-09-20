> **V0.4.0 update:** permanent impassability is now learned by terrain type, not coordinate. See `DYNAMIC_TERRAIN_RULES_V0.4.0.md`.

# FortressAgent V0.3.9 — Strict Feedback Evidence Chain

## 1. Core rule

The agent may learn only from information that its own process actually sent,
received or derived from those values.

Allowed runtime evidence:

```text
previous Experience / actual sent Decision
lastRoundRoleActionResults
errors[] received in the server response
lastSummonTreasureResult
lastCmdResult (sandbox/self-evolution channel only)
GameState / WorldMemory / StrategicMemory
```

Forbidden runtime evidence:

```text
downloaded competition log
judger-only stdout/stderr lines
"System prompt : [COMMAND_ERROR] ..." lines not present in the response payload
manual post-game analysis text
```

Logger is an output for humans. It is never an input to Memory or Policy.

---

## 2. Failure trigger

Primary trigger:

```text
lastRoundRoleActionResults[role_id] == false
```

This alone proves only:

```text
the exact action sent last round failed
```

It creates:

```text
ActionFailureLesson
+ temporary exact-action retry ban
+ Experience Outcome(action_legal=false)
+ compact action_execution_failed log event
```

It does **not** permanently mark a coordinate as impassable.

---

## 3. Permanent terrain rule requires corroboration

A permanent learned impassable cell is created only when all three conditions
hold:

```text
1. lastRoundRoleActionResults[role_id] == false
2. previous Experience proves we actually sent MOVE(role_id, x, y)
3. errors(errorCode=4).description matches the same role + MOVE + (x,y)
   and explicitly says the target is impassable terrain [terrain]
```

Only then:

```text
(x,y) -> learned impassable cell
role MOVE(x,y) -> hard forbidden
TraversabilityMap -> blocked
A* / Candidate / Legal / FinalValidator -> reject
```

The compact `command_error_learned` trace includes:

```json
"evidence_chain": [
  "lastRoundRoleActionResults=false",
  "previous_experience_exact_match",
  "server_errors(errorCode=4).description_exact_match"
]
```

---

## 4. Important channel separation

`lastCmdResult` is retained in `RuntimeFeedbackMemory` and Experience because
it is important for self-evolution/sandbox tasks.

However it is **not** parsed as a role MOVE error. This prevents text from the
sandbox command channel from accidentally poisoning movement traversability.

`server_errors` is the only received text channel used to enrich role-command
failure semantics, and only `errorCode=4` descriptions are considered.

---

## 5. Mismatched text is ignored for permanent learning

Example:

```text
actual previous action: MOVE(22,13)
role result: false
server error text: MOVE(23,14) is impassable
```

Result:

```text
MOVE(22,13) -> temporary exact retry ban
MOVE(23,14) -> NOT learned as permanent obstacle
```

The text cannot override what the agent knows it actually sent.

Likewise:

```text
role result: true
server error text: MOVE(23,14) is impassable
```

will not create a hard rule because the primary execution-failure trigger is
absent.

---

## 6. LLM safety feedback

The outbound strategic prompt receives only lessons already validated by the
strict runtime evidence chain. It never consumes downloaded log lines.

The prompt explicitly states:

```text
lastRoundRoleActionResults=false is authoritative evidence of action failure.
Only matched protocol server_errors may strengthen the reason into a permanent
terrain rule.
Never infer safety rules from downloaded logs or external judger log text.
```

The deterministic safety layers are active before and independently of the LLM.

---

## 7. Runtime flow

```text
previous actual Experience
        +
received lastRoundRoleActionResults
        |
        v
ActionFailureLesson
        |
        +--> exact retry suppression
        +--> Outcome / Learner
        +--> action_execution_failed log
        |
        + received matching errorCode=4 description
              |
              v
       CommandErrorLesson
              |
              +--> learned impassable cell
              +--> TraversabilityMap
              +--> command_error_learned log
              +--> validated LLM safety lesson
```

This keeps the direction strictly:

```text
received environment feedback -> Memory -> Policy -> Logger
```

never:

```text
Logger -> Memory
```
