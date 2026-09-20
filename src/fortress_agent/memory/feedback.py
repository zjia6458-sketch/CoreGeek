from __future__ import annotations

from collections import deque
from dataclasses import dataclass, fields, is_dataclass, replace
import json
import re
from types import MappingProxyType
from typing import Mapping

from fortress_agent.domain.action import MoveAction, ExploreAction


_IMPASSABLE_MOVE_SERVER_ERROR_RE = re.compile(
    r"role\s+(?P<role>\d+)\s+wants\s+MOVE\s+to\s*"
    r"\(\s*(?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\s*\).*?"
    r"impassable\s+terrain\s*\[(?P<terrain>[^\]]+)\]",
    re.IGNORECASE,
)

_RESOURCE_TERRAIN_TYPES = frozenset({"stone", "iron", "copper"})

RULE_SCOPE_GLOBAL = "global_terrain"
RULE_SCOPE_RESOURCE = "resource_type"
RULE_SCOPE_TASK = "task_terrain"

RULE_STATUS_ACTIVE = "active"
RULE_STATUS_DORMANT = "dormant"
RULE_STATUS_RETIRED = "retired"


def normalize_terrain_type(value: str) -> str:
    return str(value).strip().casefold()


@dataclass(frozen=True, slots=True)
class TerrainRule:
    """Runtime-learned semantic rule with an explicit lifecycle.

    The semantic key is terrain TYPE, not coordinate.  Coordinates are kept
    only as evidence.  Entity-scoped rules may become DORMANT when the entity
    lifecycle ends and REACTIVATE if the same semantic entity reappears.
    """

    terrain_type: str
    property_name: str
    property_value: str
    learned_round: int
    reason: str
    source: str
    evidence_signature: str
    evidence_target_x: int | None = None
    evidence_target_y: int | None = None
    scope: str = RULE_SCOPE_GLOBAL
    status: str = RULE_STATUS_ACTIVE
    validity_predicate: str = "always"
    last_transition_round: int | None = None
    expires_round: int | None = None
    lifecycle_reason: str = "learned"

    @property
    def normalized_terrain_type(self) -> str:
        return normalize_terrain_type(self.terrain_type)

    @property
    def signature(self) -> str:
        return (
            f"terrain:{self.normalized_terrain_type}:"
            f"{self.property_name}={self.property_value}"
        )

    @property
    def active(self) -> bool:
        return self.status == RULE_STATUS_ACTIVE

    def hard_rule(self) -> str:
        lifecycle = (
            f"scope={self.scope}; status={self.status}; "
            f"validity={self.validity_predicate}."
        )
        if self.property_name == "traversability" and self.property_value == "impassable":
            if self.status != RULE_STATUS_ACTIVE:
                return (
                    f"Runtime terrain knowledge [{self.terrain_type}] is currently "
                    f"{self.status.upper()} and MUST NOT be enforced now ({lifecycle})"
                )
            return (
                f"Authoritative received server feedback established a runtime "
                f"terrain rule: terrain type [{self.terrain_type}] is IMPASSABLE "
                f"while its lifecycle predicate is true. Never MOVE onto ANY neutral-zone "
                f"cell whose terrain type is [{self.terrain_type}] "
                f"while this rule is ACTIVE. Use an adjacent walkable interaction "
                f"cell instead. The coordinate that exposed this rule is evidence "
                f"only, not the rule key. {lifecycle}"
            )
        return (
            f"Runtime terrain rule: [{self.terrain_type}] "
            f"{self.property_name}={self.property_value}; {lifecycle}"
        )


@dataclass(frozen=True, slots=True)
class TerrainRuleTransition:
    rule_signature: str
    terrain_type: str
    round_id: int
    from_status: str
    to_status: str
    reason: str
    scope: str
    validity_predicate: str


@dataclass(frozen=True, slots=True)
class CommandErrorLesson:
    round_id: int
    role_id: str
    action: str
    target_x: int
    target_y: int
    reason: str
    terrain: str | None
    raw_text: str
    source: str

    @property
    def signature(self) -> str:
        terrain = self.terrain or "unknown"
        return (
            f"{self.role_id}:{self.action}:"
            f"{self.target_x},{self.target_y}:"
            f"{terrain}:{self.reason}"
        )

    def hard_rule(self) -> str:
        if self.terrain:
            return (
                f"Server feedback proved MOVE onto terrain type "
                f"[{self.terrain}] failed as impassable. This observation must "
                "be reconciled with the terrain rule lifecycle before use."
            )
        return (
            f"Role {self.role_id} previously received illegal MOVE feedback "
            f"for ({self.target_x},{self.target_y}); do not immediately repeat "
            "that exact action without new authoritative evidence."
        )


@dataclass(frozen=True, slots=True)
class ActionFailureLesson:
    round_id: int
    role_id: str
    action_type: str
    action_signature: str
    reason: str
    source: str
    raw_feedback: str
    retry_ban_until_round: int
    command_error_signature: str | None = None
    move_target_x: int | None = None
    move_target_y: int | None = None
    retry_scope: str = "same_role_exact_action"

    @property
    def signature(self) -> str:
        return (
            f"{self.role_id}:{self.action_type}:"
            f"{self.action_signature}:{self.reason}:"
            f"until={self.retry_ban_until_round}"
        )

    def hard_rule(self) -> str:
        if (
            self.action_type.upper() == "MOVE"
            and self.move_target_x is not None
            and self.move_target_y is not None
        ):
            return (
                f"Authoritative server feedback reported a MOVE failure at "
                f"({self.move_target_x},{self.move_target_y}) for role "
                f"{self.role_id} ({self.reason}). As a conservative team-wide "
                f"safety rule, NO role may MOVE to that coordinate through "
                f"round {self.retry_ban_until_round}."
            )
        return (
            f"Authoritative server feedback reported role {self.role_id} "
            f"action {self.action_type} failed ({self.reason}). "
            f"Do not repeat the exact action [{self.action_signature}] "
            f"through round {self.retry_ban_until_round}."
        )


@dataclass(frozen=True, slots=True)
class RuntimeFeedbackRecord:
    round_id: int
    role_action_results: Mapping[str, bool]
    last_summon_treasure_result: int | None
    command_result: str
    server_errors: tuple[tuple[int, str], ...]
    command_errors: tuple[CommandErrorLesson, ...] = ()
    new_safety_lessons: tuple[CommandErrorLesson, ...] = ()
    new_terrain_rules: tuple[TerrainRule, ...] = ()
    terrain_rule_transitions: tuple[TerrainRuleTransition, ...] = ()
    action_failures: tuple[ActionFailureLesson, ...] = ()


class RuntimeFeedbackMemoryView:
    def __init__(self, memory: "RuntimeFeedbackMemory") -> None:
        self._memory = memory

    def recent(self, limit: int = 20) -> tuple[RuntimeFeedbackRecord, ...]:
        if limit <= 0:
            return ()
        return tuple(self._memory._records)[-limit:]

    def latest(self) -> RuntimeFeedbackRecord | None:
        if not self._memory._records:
            return None
        return self._memory._records[-1]

    def latest_command_result(self) -> str:
        for record in reversed(self._memory._records):
            if record.command_result:
                return record.command_result
        return ""

    def is_action_forbidden(self, action, current_round: int) -> bool:
        role_id = str(getattr(action, "actor_id", ""))
        signature = action_signature(action)
        until = self._memory._failed_action_until.get((role_id, signature))
        return until is not None and int(current_round) <= until

    def is_move_retry_blocked(
        self,
        role_id,
        x: int,
        y: int,
        current_round: int,
    ) -> bool:
        del role_id
        until = self._memory._failed_move_until.get((int(x), int(y)))
        return until is not None and int(current_round) <= until

    def is_terrain_impassable(self, terrain_type: str) -> bool:
        rule = self._memory._terrain_rules.get(normalize_terrain_type(terrain_type))
        return (
            rule is not None
            and rule.active
            and rule.property_name == "traversability"
            and rule.property_value == "impassable"
        )

    def impassable_terrain_types(self) -> tuple[str, ...]:
        return tuple(
            rule.terrain_type
            for _, rule in sorted(self._memory._terrain_rules.items())
            if rule.active
            and rule.property_name == "traversability"
            and rule.property_value == "impassable"
        )

    def terrain_rules(self) -> tuple[TerrainRule, ...]:
        return tuple(
            rule
            for _, rule in sorted(self._memory._terrain_rules.items())
        )

    def active_terrain_rules(self) -> tuple[TerrainRule, ...]:
        return tuple(rule for rule in self.terrain_rules() if rule.active)

    def terrain_rule_history(self, limit: int = 50) -> tuple[TerrainRule, ...]:
        if limit <= 0:
            return ()
        return tuple(self._memory._terrain_rule_history)[-limit:]

    def impassable_cells(self) -> tuple[tuple[int, int, str], ...]:
        return ()

    def hard_rules(self, limit: int = 8) -> tuple[str, ...]:
        if limit <= 0:
            return ()
        terrain = list(self.active_terrain_rules())[-limit:]
        remaining = max(0, limit - len(terrain))
        failures = list(self._memory._failure_order)[-remaining:] if remaining else []
        return tuple(item.hard_rule() for item in [*terrain, *failures])

    def safety_lessons(self, limit: int = 20) -> tuple[CommandErrorLesson, ...]:
        if limit <= 0:
            return ()
        return tuple(self._memory._lesson_order)[-limit:]

    def action_failures(self, limit: int = 20) -> tuple[ActionFailureLesson, ...]:
        if limit <= 0:
            return ()
        return tuple(self._memory._failure_order)[-limit:]


class RuntimeFeedbackMemory:
    """Authoritative feedback memory plus lifecycle-managed runtime rules.

    Failure trigger:
        lastRoundRoleActionResults[role_id] == false

    Semantic promotion additionally requires exact correlation with the
    previous action and server_errors(errorCode=4).

    Learned terrain knowledge is not blindly permanent.  Resource/task rules
    are lifecycle-scoped and may become DORMANT when their entity disappears
    or becomes invalid.  Explicit successful-MOVE counter-evidence RETIRES an
    impassable terrain rule.
    """

    def __init__(
        self,
        capacity: int = 256,
        *,
        generic_retry_ban_rounds: int = 3,
    ) -> None:
        self._records: deque[RuntimeFeedbackRecord] = deque(maxlen=capacity)
        self._lesson_order: deque[CommandErrorLesson] = deque(maxlen=capacity)
        self._failure_order: deque[ActionFailureLesson] = deque(maxlen=capacity)
        self._terrain_rule_history: deque[TerrainRule] = deque(maxlen=capacity * 2)
        self._lesson_signatures: set[str] = set()
        self._terrain_rules: dict[str, TerrainRule] = {}
        self._failed_action_until: dict[tuple[str, str], int] = {}
        self._failed_move_until: dict[tuple[int, int], int] = {}
        self._generic_retry_ban_rounds = max(1, int(generic_retry_ban_rounds))

    def observe(
        self,
        state,
        *,
        previous_experiences=(),
    ) -> RuntimeFeedbackRecord:
        semantic_candidates = self._parse_server_error_candidates(state)
        previous_by_role = {
            str(exp.action.actor_id): exp
            for exp in previous_experiences
        }

        transitions = list(
            self._reconcile_terrain_rule_lifecycle(
                state,
                previous_by_role=previous_by_role,
            )
        )

        action_failures: list[ActionFailureLesson] = []
        validated_semantics: list[CommandErrorLesson] = []
        new_lessons: list[CommandErrorLesson] = []
        new_terrain_rules: list[TerrainRule] = []

        for role_id, legal in state.last_round_role_action_results.items():
            if legal:
                continue

            role_key = str(role_id)
            exp = previous_by_role.get(role_key)

            if exp is None:
                action_type = "UNKNOWN"
                signature = "unknown_previous_action"
                raw_feedback = f"lastRoundRoleActionResults[{role_key}]=false"
            else:
                action_type = str(exp.action.action_type).upper()
                signature = action_signature(exp.action)
                raw_feedback = (
                    f"lastRoundRoleActionResults[{role_key}]=false; "
                    f"previous={signature}"
                )

            semantic = self._matching_semantic_candidate(
                role_id=role_key,
                experience=exp,
                candidates=semantic_candidates,
            )

            if semantic is not None:
                validated_semantics.append(semantic)
                rule = self._learn_command_error(semantic, state)
                if rule is not None:
                    new_lessons.append(semantic)
                    new_terrain_rules.append(rule)
                reason = semantic.reason
                command_error_signature = semantic.signature
                raw_feedback += f"; server_error={semantic.raw_text}"
            else:
                reason = "role_action_result_false"
                command_error_signature = None

            retry_until = state.round_id + self._generic_retry_ban_rounds
            is_move_failure = (
                exp is not None
                and isinstance(exp.action, (MoveAction, ExploreAction))
            )
            failure = ActionFailureLesson(
                round_id=state.round_id,
                role_id=role_key,
                action_type=action_type,
                action_signature=signature,
                reason=reason,
                source="role_action_result",
                raw_feedback=raw_feedback,
                retry_ban_until_round=retry_until,
                command_error_signature=command_error_signature,
                move_target_x=(int(exp.action.x) if is_move_failure else None),
                move_target_y=(int(exp.action.y) if is_move_failure else None),
                retry_scope=(
                    "all_roles_same_move_target"
                    if is_move_failure
                    else "same_role_exact_action"
                ),
            )
            action_failures.append(failure)
            self._learn_action_failure(failure, exp)

        record = RuntimeFeedbackRecord(
            round_id=state.round_id,
            role_action_results=MappingProxyType(
                dict(state.last_round_role_action_results)
            ),
            last_summon_treasure_result=state.last_summon_treasure_result,
            command_result=state.last_command_result,
            server_errors=tuple(
                (error.error_code, error.description)
                for error in state.server_errors
            ),
            command_errors=tuple(validated_semantics),
            new_safety_lessons=tuple(new_lessons),
            new_terrain_rules=tuple(new_terrain_rules),
            terrain_rule_transitions=tuple(transitions),
            action_failures=tuple(action_failures),
        )
        self._records.append(record)
        return record

    def _learn_command_error(
        self,
        lesson: CommandErrorLesson,
        state,
    ) -> TerrainRule | None:
        if lesson.signature not in self._lesson_signatures:
            self._lesson_signatures.add(lesson.signature)
            self._lesson_order.append(lesson)

        if (
            lesson.action.upper() != "MOVE"
            or lesson.reason != "impassable_terrain"
            or not lesson.terrain
        ):
            return None

        key = normalize_terrain_type(lesson.terrain)
        existing = self._terrain_rules.get(key)
        if existing is not None and existing.status != RULE_STATUS_RETIRED:
            return None

        scope, predicate = self._infer_rule_scope_and_predicate(
            state,
            lesson.terrain,
        )
        status = self._desired_status_for_scope(
            scope=scope,
            terrain_type=lesson.terrain,
            state=state,
            current_status=RULE_STATUS_ACTIVE,
        )
        rule = TerrainRule(
            terrain_type=lesson.terrain,
            property_name="traversability",
            property_value="impassable",
            learned_round=lesson.round_id,
            reason=lesson.reason,
            source=lesson.source,
            evidence_signature=lesson.signature,
            evidence_target_x=lesson.target_x,
            evidence_target_y=lesson.target_y,
            scope=scope,
            status=status,
            validity_predicate=predicate,
            last_transition_round=lesson.round_id,
            lifecycle_reason="learned_and_validated",
        )
        self._terrain_rules[key] = rule
        self._terrain_rule_history.append(rule)
        return rule

    def _reconcile_terrain_rule_lifecycle(
        self,
        state,
        *,
        previous_by_role: Mapping[str, object],
    ) -> tuple[TerrainRuleTransition, ...]:
        transitions: list[TerrainRuleTransition] = []

        # Strong counter-evidence: a role successfully moved onto a cell that
        # the current authoritative map still labels with the learned terrain.
        successful_targets: list[tuple[int, int, str]] = []
        zone_by_position = {
            (zone.position.x, zone.position.y): zone.zone_type
            for zone in state.neutral_zones
        }
        for role_id, legal in state.last_round_role_action_results.items():
            if not legal:
                continue
            exp = previous_by_role.get(str(role_id))
            if exp is None or not isinstance(exp.action, (MoveAction, ExploreAction)):
                continue
            x, y = int(exp.action.x), int(exp.action.y)
            terrain = zone_by_position.get((x, y))
            if terrain:
                successful_targets.append((x, y, terrain))

        for key, rule in list(self._terrain_rules.items()):
            if rule.status == RULE_STATUS_RETIRED:
                continue

            contradicted = any(
                normalize_terrain_type(terrain) == key
                for _, _, terrain in successful_targets
            )
            if contradicted:
                updated = replace(
                    rule,
                    status=RULE_STATUS_RETIRED,
                    last_transition_round=state.round_id,
                    lifecycle_reason="successful_move_counterevidence",
                )
                self._terrain_rules[key] = updated
                self._terrain_rule_history.append(updated)
                transitions.append(TerrainRuleTransition(
                    rule_signature=updated.signature,
                    terrain_type=updated.terrain_type,
                    round_id=state.round_id,
                    from_status=rule.status,
                    to_status=updated.status,
                    reason="successful_move_counterevidence",
                    scope=updated.scope,
                    validity_predicate=updated.validity_predicate,
                ))
                continue

            desired = self._desired_status_for_scope(
                scope=rule.scope,
                terrain_type=rule.terrain_type,
                state=state,
                current_status=rule.status,
            )
            if desired == rule.status:
                continue

            reason = self._lifecycle_transition_reason(
                rule=rule,
                desired_status=desired,
                state=state,
            )
            updated = replace(
                rule,
                status=desired,
                last_transition_round=state.round_id,
                lifecycle_reason=reason,
            )
            self._terrain_rules[key] = updated
            self._terrain_rule_history.append(updated)
            transitions.append(TerrainRuleTransition(
                rule_signature=updated.signature,
                terrain_type=updated.terrain_type,
                round_id=state.round_id,
                from_status=rule.status,
                to_status=updated.status,
                reason=reason,
                scope=updated.scope,
                validity_predicate=updated.validity_predicate,
            ))

        return tuple(transitions)

    @staticmethod
    def _infer_rule_scope_and_predicate(state, terrain_type: str) -> tuple[str, str]:
        normalized = normalize_terrain_type(terrain_type)
        if normalized in _RESOURCE_TERRAIN_TYPES:
            return RULE_SCOPE_RESOURCE, "while_resource_type_present"

        matching_zone_positions = {
            (zone.position.x, zone.position.y)
            for zone in state.neutral_zones
            if normalize_terrain_type(zone.zone_type) == normalized
        }
        task_position_matches = any(
            task.position is not None
            and (task.position.x, task.position.y) in matching_zone_positions
            for task in state.tasks
        )
        if "taskpoint" in normalized or task_position_matches:
            # Official rules define the four TaskPoint map elements themselves
            # as permanent movement blockers. Task content may expire/cooldown,
            # but the physical TaskPoint terrain does not become walkable.
            return RULE_SCOPE_GLOBAL, "physical_taskpoint_always_blocks"

        return RULE_SCOPE_GLOBAL, "always_unless_counterevidence"

    @staticmethod
    def _desired_status_for_scope(
        *,
        scope: str,
        terrain_type: str,
        state,
        current_status: str,
    ) -> str:
        if current_status == RULE_STATUS_RETIRED:
            return RULE_STATUS_RETIRED

        normalized = normalize_terrain_type(terrain_type)

        if scope == RULE_SCOPE_GLOBAL:
            return RULE_STATUS_ACTIVE

        if scope == RULE_SCOPE_RESOURCE:
            present = any(
                resource.active
                and normalize_terrain_type(resource.resource_type) == normalized
                for resource in state.resources
            )
            if present:
                return RULE_STATUS_ACTIVE
            # Absence is authoritative only when the map snapshot is complete.
            return (
                RULE_STATUS_DORMANT
                if state.map_snapshot_complete
                else current_status
            )

        if scope == RULE_SCOPE_TASK:
            matching_zone_positions = {
                (zone.position.x, zone.position.y)
                for zone in state.neutral_zones
                if normalize_terrain_type(zone.zone_type) == normalized
            }
            if not matching_zone_positions:
                return (
                    RULE_STATUS_DORMANT
                    if state.map_snapshot_complete
                    else current_status
                )

            matching_tasks = tuple(
                task
                for task in state.tasks
                if task.position is not None
                and (task.position.x, task.position.y) in matching_zone_positions
            )
            if any(task.status != "invalid" for task in matching_tasks):
                return RULE_STATUS_ACTIVE
            # During an accepted task, some server versions may omit/reshape
            # playerTasks; preserve a matching task terrain while phaseTask is
            # explicitly active and the zone still exists.
            if state.phase_task.strip():
                return RULE_STATUS_ACTIVE
            # Explicit task records exist and all are invalid: lifecycle ended.
            if matching_tasks:
                return RULE_STATUS_DORMANT
            # A TaskPoint zone exists but the protocol gave us no task record.
            # Treat this as unknown rather than as proof of invalidity.
            return current_status

        return current_status

    @staticmethod
    def _lifecycle_transition_reason(*, rule: TerrainRule, desired_status: str, state) -> str:
        if desired_status == RULE_STATUS_ACTIVE:
            if rule.scope == RULE_SCOPE_RESOURCE:
                return "resource_type_reappeared"
            if rule.scope == RULE_SCOPE_TASK:
                return "matching_task_became_active"
            return "rule_reactivated"
        if desired_status == RULE_STATUS_DORMANT:
            if rule.scope == RULE_SCOPE_RESOURCE:
                return "resource_type_absent_from_complete_snapshot"
            if rule.scope == RULE_SCOPE_TASK:
                return "no_active_task_for_matching_terrain"
            return "lifecycle_predicate_false"
        return "lifecycle_transition"

    def _learn_action_failure(self, lesson: ActionFailureLesson, experience) -> None:
        self._failure_order.append(lesson)
        if lesson.action_signature == "unknown_previous_action":
            return
        key = (lesson.role_id, lesson.action_signature)
        self._failed_action_until[key] = max(
            lesson.retry_ban_until_round,
            self._failed_action_until.get(key, -1),
        )

        if experience is not None and isinstance(
            experience.action,
            (MoveAction, ExploreAction),
        ):
            move_key = (int(experience.action.x), int(experience.action.y))
            self._failed_move_until[move_key] = max(
                lesson.retry_ban_until_round,
                self._failed_move_until.get(move_key, -1),
            )

    def _parse_server_error_candidates(
        self,
        state,
    ) -> tuple[CommandErrorLesson, ...]:
        texts: list[tuple[str, str]] = [
            ("server_error", error.description)
            for error in state.server_errors
            if error.error_code == 4 and error.description
        ]

        lessons: list[CommandErrorLesson] = []
        seen: set[tuple[str, int, int, str]] = set()

        for source, text in texts:
            for match in _IMPASSABLE_MOVE_SERVER_ERROR_RE.finditer(text):
                role_id = match.group("role")
                x = int(match.group("x"))
                y = int(match.group("y"))
                terrain = match.group("terrain").strip()
                key = (role_id, x, y, terrain)
                if key in seen:
                    continue
                seen.add(key)
                lessons.append(CommandErrorLesson(
                    round_id=state.round_id,
                    role_id=role_id,
                    action="MOVE",
                    target_x=x,
                    target_y=y,
                    reason="impassable_terrain",
                    terrain=terrain,
                    raw_text=match.group(0),
                    source=source,
                ))

        return tuple(lessons)

    @staticmethod
    def _matching_semantic_candidate(
        *,
        role_id: str,
        experience,
        candidates: tuple[CommandErrorLesson, ...],
    ) -> CommandErrorLesson | None:
        if experience is None:
            return None

        action = experience.action
        if not isinstance(action, (MoveAction, ExploreAction)):
            return None

        for lesson in candidates:
            if lesson.role_id != role_id:
                continue
            if lesson.action.upper() != "MOVE":
                continue
            if int(action.x) != lesson.target_x or int(action.y) != lesson.target_y:
                continue
            return lesson

        return None

    def view(self) -> RuntimeFeedbackMemoryView:
        return RuntimeFeedbackMemoryView(self)


def action_signature(action) -> str:
    payload = {
        "type": type(action).__name__,
        "action_type": getattr(action, "action_type", None),
    }

    if is_dataclass(action):
        for field in fields(action):
            if field.name == "actor_id":
                continue
            payload[field.name] = _normalize(getattr(action, field.name))

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return {
            field.name: _normalize(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_normalize(item) for item in value]
    return repr(value)
