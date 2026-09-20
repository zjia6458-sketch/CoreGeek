# FortressAgent V0.5.1 — Station Defense Layout

## Authoritative 0/1/2 template

For the player's 2×2 station footprint, construction areas are derived from
Chebyshev distance to the **station footprint**, not from absolute map
coordinates:

```text
222222
211112
210012
210012
211112
222222
```

- `0`: station footprint; never a new build target.
- `1`: weapon-build ring; Gatling / Railgun / Rocket may be built here.
- `2`: wall-build ring; Wall may be built here.

For a normal 2×2 station this produces exactly:

- 4 station cells;
- 12 weapon candidate cells;
- 20 wall candidate cells.

The layout follows the station automatically after side swapping or any change
of station position. No absolute coordinates are required.

## Implementation

`src/fortress_agent/game_rules/build_area.py` now contains:

- `BuildAreaType`
- `station_footprint_cells(...)`
- `distance_to_station_footprint(...)`
- `station_defense_cells(...)`
- `StationDefenseBuildAreaPolicy`

`BuildCandidateGenerator`, `BasicLegalActionFilter`, `ActionMapper`, and
`FinalResponseValidator` all consume the same `BuildAreaPolicy`, so the 0/1/2
classification has one source of truth.

Explicit build cells / zone types remain supported as **additive overrides**
for special maps. They are no longer required for normal production maps.

## Weapon limits and costs

The official build catalog remains:

```text
Wall    : stone ×1, max 20
Gatling : 25 gold
Railgun : 25 gold
Rocket  : 25 gold
Weapons : global max 3 across all weapon types
```

The 12 weapon-ring cells are legal candidate positions, not a capacity of 12
weapons. Global weapon count remains 3.

## Opening doctrine

Default strategy preference is:

```text
first defensive weapon -> Rocket
```

This is intentionally a strategy bias, not a legality rule. When the team has
no weapon yet, `BuildRewardModel` adds a first-weapon Rocket bonus. Learning or
a later strategy may still choose a different mix when state evidence justifies
it.

## Regression contracts

Tests freeze the following behavior:

1. a central 2×2 station creates 12 weapon cells and 20 wall cells;
2. rendering the two rings produces the exact `222222 / 211112 / 210012` map;
3. weapons are rejected on wall-ring cells and walls are rejected on
   weapon-ring cells;
4. existing-weapon replacement remains legal;
5. first-weapon Rocket utility exceeds Railgun and Gatling under equal opening
   conditions;
6. Python 3.11 grammar remains valid;
7. production logging is still configured only in `main3.py`.
