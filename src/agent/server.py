from __future__ import annotations

import logging
from typing import Mapping

from fortress_agent.application.bootstrap import build_runtime
from fortress_agent.config.tuning import RuntimeLearningConfig
from fortress_agent.server.http import run_http_server
from fortress_agent.observability.logger import LogMode


def serve(
    port: int,
    *,
    log_mode: str = "medium",
    build_recipes: Mapping[str, Mapping[str, object]] | None = None,
    weapon_build_cells: tuple[tuple[int, int], ...] = (),
    wall_build_cells: tuple[tuple[int, int], ...] = (),
    weapon_build_zone_types: tuple[str, ...] = (),
    wall_build_zone_types: tuple[str, ...] = (),
    move_failure_global_ban_rounds: int = 3,
    hard_deadline_seconds: float = 3.2,
    http_outer_timeout_seconds: float = 4.2,
    strategy_thresholds: Mapping[str, float] | None = None,
    strategy_parameters: Mapping[str, float] | None = None,
    utility_weight_multipliers: Mapping[str, float] | None = None,
    runtime_learning_config: RuntimeLearningConfig | None = None,
    # 兼容 V0.5.5 以前的调用；若显式传入则覆盖 thresholds 中同名项。
    prepare_margin_rounds: int | None = None,
) -> None:
    logger = logging.getLogger()
    mode = LogMode.parse(log_mode)
    thresholds = dict(strategy_thresholds or {})
    if prepare_margin_rounds is not None:
        thresholds["prepare_margin_rounds"] = float(prepare_margin_rounds)

    if mode is LogMode.HIGH:
        logger.info(
            '{"channel":"system","event":"runtime_build",'
            '"observability":"single_root_logger","log_mode":"%s",'
            '"build_catalog":"official_or_override",'
            '"build_area_policy":"station_2x2_chebyshev_rings",'
            '"extra_weapon_build_cells":%d,'
            '"extra_wall_build_cells":%d,'
            '"move_failure_global_ban_rounds":%d,'
            '"hard_deadline_seconds":%.3f,'
            '"http_outer_timeout_seconds":%.3f}',
            mode.value,
            len(weapon_build_cells),
            len(wall_build_cells),
            move_failure_global_ban_rounds,
            hard_deadline_seconds,
            http_outer_timeout_seconds,
        )
    runtime = build_runtime(
        logger=logger,
        log_mode=log_mode,
        build_recipes=build_recipes,
        weapon_build_cells=weapon_build_cells,
        wall_build_cells=wall_build_cells,
        weapon_build_zone_types=weapon_build_zone_types,
        wall_build_zone_types=wall_build_zone_types,
        move_failure_global_ban_rounds=move_failure_global_ban_rounds,
        hard_deadline_seconds=hard_deadline_seconds,
        strategy_thresholds=thresholds,
        strategy_parameters=strategy_parameters,
        utility_weight_multipliers=utility_weight_multipliers,
        runtime_learning_config=runtime_learning_config,
    )
    run_http_server(
        port,
        host="0.0.0.0",
        runtime=runtime,
        outer_timeout_seconds=http_outer_timeout_seconds,
        logger=logger,
        log_mode=mode,
    )
