# FortressAgent V0.3.3 — Traversability & Resource Safety

## P0 invariant

Active resource cells are **not walkable**:

```text
stone
iron
copper
```

Their coordinates are interaction targets. A worker must stand on a cardinally adjacent walkable grid cell and send:

```json
{
  "action": "collect",
  "targetPos": [{"x": "resource_x", "y": "resource_y"}]
}
```

The agent must never send:

```json
{
  "action": "move",
  "targetPos": [{"x": "resource_x", "y": "resource_y"}]
}
```

because the server records an illegal move as an abnormal response.

## Single source of truth

The rule is centralized in:

```text
world.traversability.TraversabilityMap
```

`TraversabilityMap` combines:

```text
current GameState active resources
+ remembered AVAILABLE resources in WorldMemory
+ building footprints
```

and exposes:

```text
is_walkable(x, y)
is_resource_cell(x, y)
block_reason(x, y)
walkable_neighbors(x, y)
resource_access_cells(resource)
```

## Five independent safety layers

### 1. Candidate generation

`MoveCandidateGenerator` and `ExplorationCandidateGenerator` never create a move whose target is blocked.

### 2. LegalActionFilter

Even if another plugin constructs such a move manually, `BasicLegalActionFilter` rejects it.

### 3. Pathfinder

`AStarPathfinder` accepts the same `TraversabilityMap`; resource cells cannot appear inside a path or as a path goal.

For resource collection, `ResourceApproachCandidateGenerator` finds a path to one of the resource's **walkable adjacent cells**, then emits only the first safe step.

### 4. EmergencyPolicy

Emergency fallback uses the same traversability map. If a resource is adjacent it prefers `collect`; otherwise it chooses only a walkable neighboring cell.

### 5. FinalResponseValidator

The final wire-level gate reconstructs traversability from the authoritative current `GameState` and rejects:

```text
move_target_blocked
move_step_not_adjacent
collect_target_not_resource
collect_target_not_adjacent
```

Therefore a faulty strategy/candidate plugin still cannot send `move -> active resource cell` to the server.

## Example

State:

```text
Worker = (5,23)
Stone  = (4,24)
```

Manhattan distance is 2, so `collect` is not yet legal.

Safe resource access cells include:

```text
(4,23)
(5,24)
(3,24)
(4,25)
```

subject to buildings/other hard obstacles.

`ResourceApproachCandidateGenerator + A*` can emit:

```text
move(5,23 -> 4,23)
```

but never:

```text
move(5,23 -> 4,24)   # resource cell, hard-rejected
```

On the next round, if Worker is `(4,23)` and Stone remains `(4,24)`:

```text
collect(targetPos=(4,24))
```

is legal.


## V0.3.7 TaskPoint + learned impassable terrain

`challengerTaskPoint1/2` and `defenderTaskPoint1/2` are now hard interaction-only cells, identical to resource cells for movement feasibility. `TaskApproachCandidateGenerator` routes to a cardinally adjacent access cell, and `acceptTask` is generated/validated from that adjacent cell.

Additionally, strictly corroborated received server feedback of `impassable terrain [terrainType]` is promoted into a runtime `TerrainRule`: `terrainType -> traversability=impassable`. `TraversabilityMap` applies that rule to every current neutral-zone cell of the same type. The failed coordinate is evidence only; it is not a permanent blacklist key.


## V0.4.2 lifecycle note

Semantic impassable rules are enforced only while `status=ACTIVE`. Resource/task rules become `DORMANT` when their authoritative lifecycle ends. Explicit successful-MOVE counter-evidence changes a rule to `RETIRED`. TaskPoint cells tied to explicit `isValid=false` task records are released instead of remaining permanently blocked.
