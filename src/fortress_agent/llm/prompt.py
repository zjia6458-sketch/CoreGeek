from __future__ import annotations

from fortress_agent.domain.state import GameState


class StrategicPromptBuilder:
    """Build long-horizon advisory prompt with deterministic safety doctrine."""

    def build(
        self,
        state: GameState,
        *,
        learned_hard_rules: tuple[str, ...] = (),
    ) -> str:
        legend = (
            state.world_news.folk_legends
            if state.world_news is not None
            else ""
        )
        official = (
            state.world_news.official_news
            if state.world_news is not None
            else ""
        )

        learned = "\n".join(
            f"- {rule}"
            for rule in learned_hard_rules
        ) or "- none"

        return f"""
You are a strategic analyst for a game agent.
Do NOT output game commands or free-form prose.
Analyze only long-horizon implications.

HARD SYSTEM SAFETY RULES (non-negotiable):
- Never recommend MOVE onto stone/iron/copper resource cells.
- Never recommend MOVE onto an ACTIVE resource cell.
- Never recommend MOVE onto challengerTaskPoint*/defenderTaskPoint* cells.
  The four physical TaskPoint map elements always block movement; task content
  may expire or enter cooldown, but the TaskPoint terrain remains interaction-only.
- To interact with a task/resource, approach any walkable cell within Chebyshev distance 1 (8-neighborhood).
- lastRoundRoleActionResults=false is authoritative evidence that the previous
  action sent by this agent failed. If that action was MOVE(x,y), treat (x,y)
  as a temporary team-wide forbidden MOVE target: no role should retry it
  during the active safety window.
- Only server_errors received in the protocol and matched to that failed
  role/action/target may strengthen the reason into a semantic terrain rule.
- Terrain rules are keyed by TERRAIN TYPE, not by one coordinate, and have a
  lifecycle. Enforce only ACTIVE rules. Resource-scoped rules may become
  DORMANT when the resource disappears; a DORMANT rule MUST NOT block movement.
  Physical TaskPoint terrain is a permanent blocker even when task content is invalid.
- Explicit successful MOVE counter-evidence may RETIRE an impassable rule.
- Never infer safety rules from downloaded logs or external judger log text.

Learned execution-safety lessons from received protocol feedback:
{learned}

Current round: {state.round_id}
Phase: {state.phase}
Official news: {official}
Folk legends: {legend}

Return exactly one JSON object matching this contract:
{{
  "schema_version": "1.0",
  "source_round": {state.round_id},
  "recommended_mode": "keep|explore|task|prepare|defense|recovery|aggressive|conservative",
  "mode_strength": 0.0,
  "confidence": 0.0,
  "expires_after_rounds": 130,
  "claims": [
    {{
      "kind": "location_hint|resource_hint|requirement|route_hint|market_hint|threat_hint|unknown",
      "subject": "...",
      "relation": "...",
      "object": "...",
      "confidence": 0.0
    }}
  ],
  "objectives": [
    {{
      "objective_type": "explore_region|visit_position|collect_items|take_task|preserve_resources|prepare_defense|observe",
      "priority": 0.0,
      "description": "...",
      "target_position": null,
      "target_region": "north|south|east|west|center|unknown",
      "required_items": []
    }}
  ],
  "short_reason": "..."
}}

Treat folk legends as uncertain evidence, not guaranteed truth.
""".strip()
