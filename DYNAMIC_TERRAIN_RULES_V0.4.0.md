# FortressAgent V0.4.0 — Runtime Dynamic Terrain Rules

## Core correction

A server failure such as:

```text
role 20011 wants MOVE to (23,14), but target is impassable terrain [defenderTaskPoint1]
```

must not teach the permanent rule:

```text
(23,14) is permanently blocked
```

The transferable fact is:

```text
terrain type [defenderTaskPoint1]
    -> traversability = impassable
```

The coordinate is only evidence showing where the rule was discovered.

## Evidence chain

A permanent runtime terrain rule is promoted only when all three facts agree:

```text
1. lastRoundRoleActionResults[role] == false
2. previous Experience proves the agent actually sent MOVE(role, x, y)
3. received server_errors(errorCode=4).description matches the same role/action/target
   and states impassable terrain [terrain_type]
```

Only then is this rule inserted into `RuntimeFeedbackMemory`:

```python
TerrainRule(
    terrain_type="defenderTaskPoint1",
    property_name="traversability",
    property_value="impassable",
    ...
)
```

## Rule semantics

The rule key is normalized terrain type:

```text
terrain:defendertaskpoint1:traversability=impassable
```

`RuntimeFeedbackMemoryView` exposes:

```text
is_terrain_impassable(terrain_type)
impassable_terrain_types()
terrain_rules()
```

There is no permanent learned coordinate blacklist.

## Traversability application

On every turn:

```text
GameState.neutral_zones
        +
RuntimeFeedbackMemory.impassable_terrain_types()
        ↓
TraversabilityMap.from_state_and_memory()
```

For each current neutral zone:

```python
if zone.zone_type in learned_impassable_terrain_types:
    block(zone.position)
```

Therefore if the first failure occurs at:

```text
mysteryGate @ (5,4)
```

and a later round contains:

```text
mysteryGate @ (30,9)
mysteryGate @ (31,9)
```

both later cells are blocked automatically.

Conversely, if `(5,4)` later becomes an ordinary walkable terrain type, that
coordinate is not permanently blocked by the old lesson.

## Short-term retry safety remains coordinate-specific

`lastRoundRoleActionResults=false` still creates a temporary exact-action retry
ban. This protects the anomaly budget even before a semantic reason is known.

So there are two different memories:

```text
Short-term execution protection:
role + exact action/target -> retry ban for N rounds

Long-term environment knowledge:
terrain_type -> traversability=impassable
```

This distinction is intentional.

## Human-facing log

Compact mode emits:

```json
{
  "kind": "terrain_rule_learned",
  "data": {
    "terrain_type": "mysteryGate",
    "property": "traversability",
    "value": "impassable",
    "scope": "all_neutral_zones_of_this_type",
    "evidence_example_target": [4,5],
    "rule_signature": "terrain:mysterygate:traversability=impassable"
  }
}
```

The coordinate appears only under `evidence_example_target`.

## LLM advisory

The LLM receives the already-validated semantic rule:

```text
terrain type [mysteryGate] is IMPASSABLE.
Never MOVE onto ANY neutral-zone cell whose terrain type is [mysteryGate].
```

The deterministic Traversability layer applies the rule immediately; LLM
advisory is only synchronized afterward and is never required for safety.
