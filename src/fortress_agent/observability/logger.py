from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import json
import logging
from typing import Mapping

from .trace import TraceEvent, TraceSink


class LogMode(str, Enum):
    """生产日志三级模式。

    LOW：仅输出每回合 ``=====START=====`` / ``=====END=======`` 之间的最小核心摘要；
    MEDIUM：输出完整的人类可读回合摘要（默认）；
    HIGH：MEDIUM 摘要 + 全量 trace/io/experience/world_event 结构化日志。

    ``compact``/``full`` 仅作为旧配置兼容别名，分别映射到 MEDIUM/HIGH。
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    COMPACT = "medium"
    FULL = "high"

    @classmethod
    def parse(cls, value: str | "LogMode") -> "LogMode":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        normalized = {"compact": "medium", "full": "high"}.get(normalized, normalized)
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                f"unsupported log mode {value!r}; expected 'low', 'medium', or 'high'"
            ) from exc


def to_loggable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: to_loggable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): to_loggable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_loggable(item) for item in value]
    return repr(value)


_COMPACT_TRACE_KINDS = frozenset({
    "request_parse_failed",
    "server_feedback_observed",
    "terrain_rule_learned",
    "terrain_rule_lifecycle_changed",
    "action_execution_failed",
    "deadline_fallback",
    "response_delivery_abandoned",
    "previous_response_timeout_observed",
    "strategy_selected",
    "task_session_planned",
    "task_skill_learned",
    "team_empty_control_fallback",
    "team_decision_planned",
    "round_human_summary",
    "final_response_validated",
    "outcome_attached",
    "folk_legend_observed",
    "llm_advisory_rejected",
    "llm_advisory_accepted",
    "turn_completed",
})

_COMPACT_WORLD_EVENTS = frozenset({
    "ResourceDiscovered",
    "ResourceUpdated",
    "ResourceDepleted",
    "ResourceReplenished",
})


class LoggerJsonWriter:
    """Structured records routed to the one logger configured by main3.py.

    Log mode only changes human-facing projection. It never changes the
    operational Memory/Event/Experience objects that are updated before this
    writer is called.
    """

    def __init__(
        self,
        *,
        channel: str,
        logger: logging.Logger | None = None,
        level: int = logging.INFO,
        mode: LogMode | str = LogMode.MEDIUM,
    ) -> None:
        self._channel = channel
        self._logger = logger if logger is not None else logging.getLogger()
        self._level = level
        self._mode = LogMode.parse(mode)

    @property
    def mode(self) -> LogMode:
        return self._mode

    def write(self, payload: Mapping[str, object]) -> None:
        record = {
            "channel": self._channel,
            **to_loggable(payload),
        }
        # LOW/MEDIUM 只允许 LoggerTraceSink 直接输出 human round summary。
        # 所有结构化 channel 在这两个模式下都静默，避免日志再次膨胀。
        if self._mode in {LogMode.LOW, LogMode.MEDIUM}:
            return
        try:
            self._logger.log(
                self._level,
                "%s",
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=False,
                ),
            )
        except Exception:
            try:
                self._logger.exception(
                    '{"channel":"system","event":"structured_log_failure"}'
                )
            except Exception:
                pass

    def _compact(self, record: dict[str, object]) -> dict[str, object] | None:
        channel = self._channel

        if channel == "trace":
            event = record.get("event")
            if isinstance(event, dict):
                return {
                    "channel": "trace",
                    "record_type": "trace",
                    "event": {
                        "kind": event.get("kind"),
                        "round_id": event.get("round_id"),
                        "data": event.get("data", {}),
                        "correlation_id": event.get("correlation_id"),
                    },
                }
            return record

        if channel == "world_event":
            event_type = str(record.get("event_type", ""))
            if event_type not in _COMPACT_WORLD_EVENTS:
                return None
            return record

        if channel == "io":
            record_type = record.get("record_type")
            if record_type == "request":
                # Request facts are already represented by feedback/strategy
                # records. Avoid duplicating the whole server payload.
                return None
            if record_type == "response":
                payload = record.get("payload")
                if isinstance(payload, dict):
                    return {
                        "channel": "io",
                        "record_type": "response",
                        "correlation_id": record.get("correlation_id"),
                        "round_id": record.get("round_id"),
                        "roleCommandMap": payload.get("roleCommandMap", {}),
                        "prompt_present": bool(payload.get("prompt")),
                        "executeCmd": payload.get("executeCmd", ""),
                    }
            return record

        if channel == "experience":
            record_type = record.get("record_type")
            if record_type == "experience":
                exp = record.get("experience")
                if not isinstance(exp, dict):
                    return record
                predicted = exp.get("predicted_utility") or {}
                action = exp.get("action") or {}
                return {
                    "channel": "experience",
                    "record_type": "experience",
                    "experience_id": exp.get("experience_id"),
                    "decision_id": exp.get("decision_id"),
                    "correlation_id": exp.get("correlation_id"),
                    "round_id": exp.get("round_id"),
                    "policy_version": exp.get("policy_version"),
                    "strategy_id": exp.get("strategy_id"),
                    "actor_id": action.get("actor_id"),
                    "action_type": action.get("action_type"),
                    "predicted_utility": predicted.get("total"),
                }
            if record_type == "outcome":
                outcome = record.get("outcome")
                if not isinstance(outcome, dict):
                    return record
                reward = outcome.get("reward") or {}
                return {
                    "channel": "experience",
                    "record_type": "outcome",
                    "outcome_id": outcome.get("outcome_id"),
                    "correlation_id": outcome.get("correlation_id"),
                    "start_round": outcome.get("start_round"),
                    "end_round": outcome.get("end_round"),
                    "reward_total": reward.get("total"),
                    "action_legal": outcome.get("action_legal"),
                    "server_error_codes": outcome.get("server_error_codes", []),
                    "server_error_messages": outcome.get("server_error_messages", []),
                    "command_error_signatures": outcome.get("command_error_signatures", []),
                    "terrain_rule_signatures": outcome.get("terrain_rule_signatures", []),
                    "action_failure_signatures": outcome.get("action_failure_signatures", []),
                    "command_result_present": bool(outcome.get("execute_cmd_result")),
                }
            return None

        return record

    def close(self) -> None:
        return


class LoggerTraceSink(TraceSink):
    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        mode: LogMode | str = LogMode.MEDIUM,
    ) -> None:
        self._mode = LogMode.parse(mode)
        self._logger = logger if logger is not None else logging.getLogger()
        self._writer = LoggerJsonWriter(
            channel="trace",
            logger=self._logger,
            mode=self._mode,
        )

    def emit(self, event: TraceEvent) -> None:
        if event.kind == "round_human_summary":
            self._emit_round_human_summary(event)
            return
        if self._mode in {LogMode.LOW, LogMode.MEDIUM}:
            return
        self._writer.write({
            "record_type": "trace",
            "event": event,
        })

    def _emit_round_human_summary(self, event: TraceEvent) -> None:
        data = dict(event.data)
        lines = [
            "=====START=====",
            f"Round {event.round_id} (Day {data.get('day')}, {data.get('phase')}), "
            f"Gold: {data.get('gold')}, Score: {data.get('score')}",
        ]

        def append_learned_overlay() -> None:
            """把当前相对 Learned Overlay 放在每回合日志的最后。

            比赛环境只保证 stdout 可下载，因此即使当前不做 JSONL 持久化，也必须让
            人类仅凭日志就能知道当前策略相对 Base Config 学到了多少。
            """
            rows = list(data.get("learned_overlay") or [])
            if not rows:
                lines.append("LearnedOverlay: none")
                return
            lines.append("LearnedOverlay:")
            for row in rows:
                ratio = float(row.get("relative_overlay") or 0.0)
                base = float(row.get("base_value") or 0.0)
                overlay = float(row.get("overlay_value") or 0.0)
                effective = float(row.get("effective_value") or 0.0)
                lines.append(
                    f"  {row.get('path')}: {ratio:+.2%} "
                    f"(base={base:.3f}, overlay={overlay:+.3f}, effective={effective:.3f})"
                )

        # LOW 只保留决策核心：回合、最终动作、任务顶层动作。
        if self._mode is LogMode.LOW:
            for action in data.get("actions", []):
                lines.append(f"Role {action.get('actor_id')}: {action.get('detail')}")
            execute_cmd = str(data.get("execute_cmd") or "")
            if execute_cmd:
                lines.append(f"ExecCmd: {execute_cmd}")
            task_stage = str(data.get("task_stage") or "")
            if task_stage:
                lines.append(f"TaskStage: {task_stage}")
            for update in data.get("policy_updates", []):
                lines.append(
                    "LearningUpdate: "
                    f"v{update.get('policy_version')} {update.get('component')}.{update.get('key')} "
                    f"{float(update.get('old_value') or 0.0):.3f}->{float(update.get('new_value') or 0.0):.3f} "
                    f"overlay={float(update.get('new_overlay_ratio') or 0.0):+.2%}"
                )
            append_learned_overlay()
            lines.append("=====END=======")
        else:
            lines.append(
                f"Strategy: {data.get('strategy')} | Nodes: "
                + " -> ".join(str(x) for x in data.get("node_chain", []))
            )
            last_cmd_result = str(data.get("last_cmd_result") or "")
            if last_cmd_result:
                preview = last_cmd_result if len(last_cmd_result) <= 800 else last_cmd_result[:800] + "..."
                lines.append("  LastCmdResult: " + preview.replace("\n", "\n    "))
            economy_roles = dict(data.get("economy_roles") or {})
            for role in data.get("roles", []):
                doctrine = economy_roles.get(str(role.get("id")), "")
                doctrine_text = f" role={doctrine}" if doctrine else ""
                lines.append(
                    f"  [us] {role.get('kind')} id={role.get('id')} "
                    f"pos=({role.get('x')},{role.get('y')}) hp={role.get('hp')}"
                    f"{doctrine_text}"
                )
            for building in data.get("buildings", []):
                level = building.get("level")
                level_text = f" level={level}" if level is not None else ""
                lines.append(
                    f"  [us] {building.get('kind')} id={building.get('id')} "
                    f"pos=({building.get('x')},{building.get('y')}) hp={building.get('hp')}"
                    f"{level_text}"
                )
            for action in data.get("actions", []):
                lines.append(
                    f"  Role {action.get('actor_id')}: {action.get('detail')} "
                    f"[utility={float(action.get('utility') or 0.0):.3f}]"
                )
                raw = dict(action.get("utility_raw") or {})
                weights = dict(action.get("utility_weights") or {})
                if raw and weights:
                    keys = ("score","survival","economy","information","position","task","time_cost","risk")
                    parts = []
                    for key in keys:
                        if key not in raw:
                            continue
                        sign = "-" if key in {"time_cost","risk"} else "+"
                        parts.append(f"{sign}{key}:{float(raw[key]):.2f}*{float(weights.get(key,1.0)):.2f}")
                    lines.append("    UtilityFormula: U=" + " ".join(parts))
                resource_formula = str(action.get("resource_formula") or "")
                if resource_formula:
                    lines.append("    ResourceFormula: " + resource_formula)
            execute_cmd = str(data.get("execute_cmd") or "")
            if execute_cmd:
                lines.append(f"  ExecCmd: {execute_cmd}")
            task_stage = str(data.get("task_stage") or "")
            if task_stage:
                remaining = data.get("task_remaining_rounds")
                anchor = str(data.get("task_anchor_zone_type") or "")
                extra = []
                if remaining is not None:
                    extra.append(f"remaining={remaining}")
                if anchor:
                    extra.append(f"anchor={anchor}")
                suffix = " [" + ", ".join(extra) + "]" if extra else ""
                lines.append(f"  TaskStage: {task_stage}{suffix}")
            for update in data.get("policy_updates", []):
                lines.append(
                    "  LearningUpdate: "
                    f"v{update.get('policy_version')} {update.get('component')}.{update.get('key')} "
                    f"{float(update.get('old_value') or 0.0):.3f}->{float(update.get('new_value') or 0.0):.3f} "
                    f"overlay={float(update.get('new_overlay_ratio') or 0.0):+.2%} "
                    f"by={update.get('proposer')} confidence={float(update.get('confidence') or 0.0):.2f} "
                    f"next={update.get('next_update_round')}"
                )
            lines.append(f"  DeadlineRemaining: {data.get('deadline_remaining')}s")
            append_learned_overlay()
            lines.append("=====END=======")
        try:
            self._logger.info("\n%s", "\n".join(lines))
        except Exception:
            pass

    def close(self) -> None:
        return
