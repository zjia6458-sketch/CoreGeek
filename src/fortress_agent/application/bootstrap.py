from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fortress_agent.application.runtime import (
    FortressAgentRuntime,
)
from fortress_agent.events.store import (
    InMemoryEventStore,
    JournaledEventStore,
    JsonlEventStore,
)
from fortress_agent.learning.experience.store import (
    InMemoryExperienceStore,
    JournaledExperienceStore,
)
from fortress_agent.observation.memory_engine import (
    WorldMemoryEngine,
)
from fortress_agent.memory.recovery import (
    WorldMemoryRecovery,
)
from fortress_agent.memory.feedback import RuntimeFeedbackMemory
from fortress_agent.config.tuning import (
    RuntimeLearningConfig, merged_parameters, merged_thresholds,
    merged_utility_weight_multipliers,
)
from fortress_agent.game_rules.build_area import StationDefenseBuildAreaPolicy
from fortress_agent.memory.snapshot import (
    JsonWorldMemorySnapshotStore,
)
from fortress_agent.observability.io import (
    IoJournal,
)
from fortress_agent.observability.journal import (
    QueueJsonlWriter,
)
from fortress_agent.observability.logger import (
    LoggerJsonWriter,
    LoggerTraceSink,
    LogMode,
)
from fortress_agent.observability.sinks import (
    QueueJsonlTraceSink,
)


def build_runtime(
    *,
    logger: logging.Logger | None = None,
    log_mode: LogMode | str = LogMode.MEDIUM,
    build_recipes: dict[str, dict[str, object]] | None = None,
    weapon_build_cells: tuple[tuple[int, int], ...] = (),
    wall_build_cells: tuple[tuple[int, int], ...] = (),
    weapon_build_zone_types: tuple[str, ...] = (),
    wall_build_zone_types: tuple[str, ...] = (),
    move_failure_global_ban_rounds: int = 3,
    hard_deadline_seconds: float = 3.2,
    strategy_thresholds: dict[str, float] | None = None,
    strategy_parameters: dict[str, float] | None = None,
    utility_weight_multipliers: dict[str, float] | None = None,
    runtime_learning_config: RuntimeLearningConfig | None = None,
    prepare_margin_rounds: int | None = None,
) -> FortressAgentRuntime:
    """构造 ``main3.py`` 使用的生产 Runtime。

    可观测性约束：
    - 生产环境不创建 runtime JSONL；
    - 不创建隐藏 snapshot 文件；
    - 不注册私有 logging handler；
    - 所有记录统一进入 main3.py 配置的 root logger。

    WorldMemory 与 Experience 的真实运行状态保存在比赛进程内存中，日志只是投影。
    """

    root_logger = (
        logger
        if logger is not None
        else logging.getLogger()
    )

    mode = LogMode.parse(log_mode)

    trace = LoggerTraceSink(
        logger=root_logger,
        mode=mode,
    )

    event_store = JournaledEventStore(
        InMemoryEventStore(),
        LoggerJsonWriter(
            channel="world_event",
            logger=root_logger,
            mode=mode,
        ),
    )

    memory = WorldMemoryEngine(
        event_store=event_store,
    )

    experiences = JournaledExperienceStore(
        InMemoryExperienceStore(),
        LoggerJsonWriter(
            channel="experience",
            logger=root_logger,
            mode=mode,
        ),
    )

    io_journal = IoJournal(
        LoggerJsonWriter(
            channel="io",
            logger=root_logger,
            mode=mode,
        )
    )

    from fortress_agent.policy.build_catalog import BuildCatalog
    build_catalog = BuildCatalog.from_mapping(build_recipes)
    build_area_policy = StationDefenseBuildAreaPolicy.from_config(
        weapon_cells=weapon_build_cells,
        wall_cells=wall_build_cells,
        weapon_zone_types=weapon_build_zone_types,
        wall_zone_types=wall_build_zone_types,
    )

    from fortress_agent.domain.policy_state import PolicyState

    return FortressAgentRuntime(
        memory_engine=memory,
        experience_store=experiences,
        trace_sink=trace,
        io_journal=io_journal,
        build_catalog=build_catalog,
        build_area_policy=build_area_policy,
        feedback_memory=RuntimeFeedbackMemory(
            generic_retry_ban_rounds=move_failure_global_ban_rounds,
        ),
        policy_state=PolicyState.create(
            thresholds=merged_thresholds({
                **dict(strategy_thresholds or {}),
                **({"prepare_margin_rounds": float(prepare_margin_rounds)} if prepare_margin_rounds is not None else {}),
            }),
            parameters=merged_parameters(strategy_parameters),
            utility_weights=merged_utility_weight_multipliers(utility_weight_multipliers),
        ),
        runtime_learning_config=runtime_learning_config,
        # No production file snapshot: the judger only exposes stdout logs,
        # and a hidden snapshot file cannot be inspected/downloaded.
        world_snapshot_store=None,
        hard_deadline_seconds=hard_deadline_seconds,
    )


# -----------------------------------------------------------------------
# Explicit LOCAL/OFFLINE compatibility path.
# Not used by main3.py or agent.server.serve().
# Kept because recovery/replay tests and local development still benefit from
# persistent fixtures.
# -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RuntimeLogPaths:
    root: Path
    trace: Path
    world_events: Path
    experience: Path
    io: Path
    world_snapshot: Path


def runtime_log_paths(
    data_dir: str | Path,
) -> RuntimeLogPaths:
    root = Path(data_dir)
    return RuntimeLogPaths(
        root=root,
        trace=root / "trace.jsonl",
        world_events=root / "world_events.jsonl",
        experience=root / "experience.jsonl",
        io=root / "io.jsonl",
        world_snapshot=root / "world_snapshot.json",
    )


def build_logged_runtime(
    data_dir: str | Path = "runtime_data",
) -> FortressAgentRuntime:
    """Local/offline-only file-journal runtime.

    Production MUST use :func:`build_runtime`. This function is intentionally
    retained for replay/recovery development and tests, not for the judger.
    """

    paths = runtime_log_paths(data_dir)
    paths.root.mkdir(
        parents=True,
        exist_ok=True,
    )

    trace = QueueJsonlTraceSink(
        paths.trace
    )

    snapshot_store = (
        JsonWorldMemorySnapshotStore(
            paths.world_snapshot
        )
    )
    historical_events = JsonlEventStore(
        paths.world_events
    )
    recovered_memory, last_round = (
        WorldMemoryRecovery(
            snapshot_store=snapshot_store,
            event_store=historical_events,
        ).recover()
    )

    event_store = JournaledEventStore(
        InMemoryEventStore(),
        QueueJsonlWriter(
            paths.world_events
        ),
    )
    memory = WorldMemoryEngine(
        memory=recovered_memory,
        event_store=event_store,
        last_observed_round=last_round,
    )

    experiences = JournaledExperienceStore(
        InMemoryExperienceStore(),
        QueueJsonlWriter(
            paths.experience
        ),
    )

    io_journal = IoJournal(
        QueueJsonlWriter(
            paths.io
        )
    )

    return FortressAgentRuntime(
        memory_engine=memory,
        experience_store=experiences,
        trace_sink=trace,
        io_journal=io_journal,
        world_snapshot_store=snapshot_store,
    )
