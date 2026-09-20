# FortressAgent V0.4.1 — Team-wide MOVE Retry Guard

## 1. Motivation

The competition allows only five abnormal/illegal command failures. Therefore a
failed MOVE target must not be rediscovered independently by every role.

If role `20011` receives authoritative execution feedback:

```text
lastRoundRoleActionResults["20011"] = false
```

for the actual previously-sent action:

```text
MOVE -> (23,14)
```

FortressAgent now installs a **temporary team-wide MOVE target guard**:

```text
ALL roles: MOVE(23,14) forbidden through round N
```

This is intentionally stronger than the previous actor-local retry guard.

## 2. Two different kinds of learned safety

### Temporary execution protection

Evidence required:

```text
previous action actually sent by us
+
lastRoundRoleActionResults[role] == false
```

Result:

```text
(x,y) temporarily blocked as a MOVE target for ALL roles
```

Default duration is configured in root-level `main3.py`:

```python
MOVE_FAILURE_GLOBAL_BAN_ROUNDS = 3
```

This rule is conservative and temporary because `false` alone does not prove
that the coordinate is permanently impassable.

### Permanent semantic terrain rule

Additional matched evidence is required:

```text
server_errors(errorCode=4).description
+
role/action/target exact match
+
impassable terrain [terrainType]
```

Result:

```text
terrainType -> traversability=impassable
```

For example:

```text
defenderTaskPoint1 -> impassable
```

This permanent rule generalizes to every future neutral-zone cell of that
terrain type, regardless of coordinate.

## 3. Runtime representation

`RuntimeFeedbackMemory` retains two independent stores:

```text
_failed_move_until[(x,y)]
    temporary, team-wide coordinate protection

_terrain_rules[normalized_terrain_type]
    permanent semantic terrain knowledge
```

The role id is deliberately NOT part of `_failed_move_until`.

The compatibility API remains:

```python
feedback_memory.is_move_retry_blocked(
    role_id,
    x,
    y,
    current_round,
)
```

but `role_id` is ignored for the MOVE-coordinate guard. This avoids changing
all Candidate/Legal/Validator call sites while enforcing team-wide semantics.

## 4. Enforcement layers

The same team-wide temporary MOVE guard is checked by:

```text
navigation candidate generators
BasicLegalActionFilter
FinalResponseValidator
```

Therefore even if another role or a future plugin independently proposes the
same coordinate, it cannot reach the server during the protection window.

## 5. Human log evidence

Compact logs keep `action_execution_failed` and now include:

```json
{
  "retry_scope": "all_roles_same_move_target",
  "move_target": [23, 14],
  "retry_ban_until_round": 19
}
```

This makes it explicit that the protection is team-wide rather than local to
the role that first discovered the failure.

## 6. Why the rule expires

A bare `role_action_results=false` can be caused by transient conditions. Thus
it is unsafe to infer:

```text
coordinate permanently impassable
```

from that signal alone.

After the temporary window expires, the coordinate becomes usable again unless
stronger evidence has promoted its terrain type into a permanent
`TerrainRule`.
