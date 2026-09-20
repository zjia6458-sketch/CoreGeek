# FortressAgent V0.4.2 — Dynamic Rule Lifecycle

## Goal

Runtime-learned rules must change with the world. A rule is not necessarily
valid forever merely because it was once correct.

V0.4.2 introduces an explicit lifecycle for semantic terrain rules:

```text
ACTIVE
  ↓ lifecycle predicate becomes false
DORMANT
  ↓ matching entity/lifecycle becomes active again
ACTIVE

ACTIVE/DORMANT
  ↓ authoritative successful-MOVE counter-evidence
RETIRED
```

`DORMANT` is deliberately different from deletion. The rule no longer affects
agent decisions, but its evidence remains available for audit and future
reactivation.

---

## Rule model

A runtime `TerrainRule` now contains:

```text
terrain_type
property_name
property_value
scope
status
validity_predicate
learned_round
last_transition_round
expires_round
reason/source/evidence
lifecycle_reason
```

The coordinate that exposed the rule remains evidence only. It is never the
semantic rule key.

---

## Scopes

### `global_terrain`

Use for terrain whose meaning is independent of a short-lived entity.

```text
validity = always_unless_counterevidence
```

Absence from one map snapshot does not invalidate the learned semantic fact.

### `resource_type`

Used for `stone`, `iron`, `copper` rules.

```text
ACTIVE  while at least one active resource of that type exists
DORMANT when a complete authoritative map snapshot contains none
ACTIVE  again if the resource type reappears
```

This is in addition to ordinary `ResourceMemory` lifecycle tracking. An active
resource cell itself remains non-walkable even without a learned terrain rule.

### `task_terrain`

Used for TaskPoint-like terrain or a terrain observed at a task position.

```text
ACTIVE  while a matching valid task is present
DORMANT when matching task records are explicitly invalid
DORMANT when the matching zone disappears from a complete snapshot
ACTIVE  again when a matching valid task reappears
```

If a TaskPoint zone is visible but the server supplies no matching task record,
the agent stays conservative. Missing task metadata is not treated as proof
that the cell became walkable.

---

## TaskPoint static safety lifecycle

TaskPoint cells are no longer unconditionally blocked forever.

If the protocol explicitly supplies:

```text
playerTask.isValid = false
```

for the task at that TaskPoint, and there is no active `phaseTask` requiring it,
the TaskPoint is released from the static task-cell obstacle set.

Therefore:

```text
valid task -> TaskPoint interaction-only / non-walkable
invalid task -> TaskPoint may become walkable
```

The learned semantic rule becomes `DORMANT` at the same time and therefore does
not re-block the released cell.

---

## Counter-evidence

A semantic impassable rule can be wrong later because the environment changed.

Strong counter-evidence is:

```text
we actually sent MOVE(x,y)
+ lastRoundRoleActionResults[role] == true
+ current authoritative map still labels (x,y) with the learned terrain type
```

Then the rule becomes:

```text
RETIRED
reason = successful_move_counterevidence
```

A retired rule is not enforced and does not automatically reactivate.

---

## Short-term failure guards are separate

The V0.4.1 team-wide retry guard remains independent:

```text
MOVE(x,y) failed
-> every role temporarily avoids MOVE(x,y)
```

That guard expires by round number. It is not a semantic terrain rule.

Long-term knowledge remains:

```text
terrain type -> property + lifecycle
```

This separation prevents a transient command failure from becoming permanent
world knowledge while still protecting the five-exception budget immediately.

---

## Human-facing compact logs

V0.4.2 adds:

```text
terrain_rule_lifecycle_changed
```

Example:

```json
{
  "kind": "terrain_rule_lifecycle_changed",
  "data": {
    "terrain_type": "defenderTaskPoint1",
    "from_status": "active",
    "to_status": "dormant",
    "reason": "no_active_task_for_matching_terrain",
    "scope": "task_terrain",
    "validity_predicate": "while_active_task_on_matching_terrain_present"
  }
}
```

The log mode does not affect rule lifecycle or Memory contents.

---

## Runtime decision rule

Only `ACTIVE` rules are returned by:

```python
feedback_memory.impassable_terrain_types()
feedback_memory.is_terrain_impassable(...)
feedback_memory.hard_rules()
```

`DORMANT` and `RETIRED` entries remain in `terrain_rules()` / rule history for
audit, but do not affect Traversability, Candidate generation, pathfinding,
Legal filtering or FinalResponseValidator.
