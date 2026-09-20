from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _readonly(data: Mapping[str, float] | None = None):
    return MappingProxyType(dict(data or {}))


def _overlay_path(component: str, key: str | None = None) -> str:
    if component == "risk_weight":
        return "risk_weight"
    if key is None:
        raise ValueError(f"overlay key is required for component={component}")
    return f"{component}.{key}"


def _apply_overlay(
    component: str,
    base: Mapping[str, float],
    learned_overlay: Mapping[str, float],
) -> Mapping[str, float]:
    """按 Base × (1 + relative_overlay) 计算运行时有效值。

    Learned Overlay 永远保存“相对 Base 的比例”，而不是绝对增量。例如：
    Base=4、Effective=4.2 时保存 +0.05；未来把 Base 改为 8，复用同一个
    +0.05 后 Effective 自动变为 8.4，绝对增量也从 0.2 变为 0.4。
    """
    effective: dict[str, float] = {}
    for key, base_value in base.items():
        ratio = float(learned_overlay.get(_overlay_path(component, key), 0.0))
        effective[str(key)] = float(base_value) * (1.0 + ratio)
    return _readonly(effective)


@dataclass(frozen=True, slots=True)
class PolicyState:
    """生产策略状态 = Base Config + Learned Overlay。

    ``base_*`` 保存 main3.py / 默认配置给出的人工基线；``learned_overlay`` 只保存
    在线学习得到的相对比例。``thresholds`` / ``utility_weights`` / ``parameters`` 等
    是二者合成后的 Effective Config，业务代码始终读取 Effective Config。

    当前版本不做 JSONL 持久化：进程重启后 Overlay 从空开始。保留相对比例模型是
    为了保证未来即使引入持久化，人工修改 Base Config 后学习效果也能按比例缩放，
    而不是用旧的绝对值覆盖新配置。
    """

    version: int = 1

    # 人工/默认基线。运行时学习绝不直接修改这些字段。
    base_thresholds: Mapping[str, float] = field(default_factory=lambda: _readonly())
    base_utility_weights: Mapping[str, float] = field(default_factory=lambda: _readonly())
    base_parameters: Mapping[str, float] = field(default_factory=lambda: _readonly())
    base_strategy_priors: Mapping[str, float] = field(default_factory=lambda: _readonly())
    base_risk_weight: float = 1.0

    # 扁平路径 -> 相对比例，例如 ``thresholds.prepare_margin_rounds: -0.05``。
    learned_overlay: Mapping[str, float] = field(default_factory=lambda: _readonly())

    # 业务侧读取的有效配置 = Base × (1 + Learned Overlay)。
    thresholds: Mapping[str, float] = field(default_factory=lambda: _readonly())
    utility_weights: Mapping[str, float] = field(default_factory=lambda: _readonly())
    parameters: Mapping[str, float] = field(default_factory=lambda: _readonly())
    strategy_priors: Mapping[str, float] = field(default_factory=lambda: _readonly())
    risk_weight: float = 1.0

    @classmethod
    def create(
        cls,
        *,
        version: int = 1,
        thresholds: Mapping[str, float] | None = None,
        utility_weights: Mapping[str, float] | None = None,
        parameters: Mapping[str, float] | None = None,
        strategy_priors: Mapping[str, float] | None = None,
        risk_weight: float = 1.0,
        learned_overlay: Mapping[str, float] | None = None,
    ) -> "PolicyState":
        base_thresholds = _readonly(thresholds)
        base_utility_weights = _readonly(utility_weights)
        base_parameters = _readonly(parameters)
        base_strategy_priors = _readonly(strategy_priors)
        overlay = _readonly(learned_overlay)
        risk_ratio = float(overlay.get("risk_weight", 0.0))
        return cls(
            version=version,
            base_thresholds=base_thresholds,
            base_utility_weights=base_utility_weights,
            base_parameters=base_parameters,
            base_strategy_priors=base_strategy_priors,
            base_risk_weight=float(risk_weight),
            learned_overlay=overlay,
            thresholds=_apply_overlay("thresholds", base_thresholds, overlay),
            utility_weights=_apply_overlay("utility_weights", base_utility_weights, overlay),
            parameters=_apply_overlay("parameters", base_parameters, overlay),
            strategy_priors=_apply_overlay("strategy_priors", base_strategy_priors, overlay),
            risk_weight=float(risk_weight) * (1.0 + risk_ratio),
        )

    def base_value(self, component: str, key: str = "") -> float | None:
        if component == "thresholds":
            return float(self.base_thresholds[key]) if key in self.base_thresholds else None
        if component == "utility_weights":
            return float(self.base_utility_weights[key]) if key in self.base_utility_weights else None
        if component == "parameters":
            return float(self.base_parameters[key]) if key in self.base_parameters else None
        if component == "strategy_priors":
            return float(self.base_strategy_priors[key]) if key in self.base_strategy_priors else None
        if component == "risk_weight":
            return float(self.base_risk_weight)
        return None

    def overlay_ratio(self, component: str, key: str = "") -> float:
        return float(self.learned_overlay.get(_overlay_path(component, key or None), 0.0))

    def effective_value(self, component: str, key: str = "") -> float | None:
        if component == "thresholds":
            return float(self.thresholds[key]) if key in self.thresholds else None
        if component == "utility_weights":
            return float(self.utility_weights[key]) if key in self.utility_weights else None
        if component == "parameters":
            return float(self.parameters[key]) if key in self.parameters else None
        if component == "strategy_priors":
            return float(self.strategy_priors[key]) if key in self.strategy_priors else None
        if component == "risk_weight":
            return float(self.risk_weight)
        return None

    def overlay_snapshot(self) -> tuple[dict[str, float | str], ...]:
        """返回可直接写入 logger 的当前 Learned Overlay 快照。"""
        rows: list[dict[str, float | str]] = []
        for path, ratio in sorted(self.learned_overlay.items()):
            if path == "risk_weight":
                component, key = "risk_weight", ""
            else:
                component, sep, key = path.partition(".")
                if not sep:
                    continue
            base = self.base_value(component, key)
            effective = self.effective_value(component, key)
            if base is None or effective is None:
                continue
            rows.append({
                "path": path,
                "component": component,
                "key": key,
                "base_value": float(base),
                "relative_overlay": float(ratio),
                "overlay_value": float(base) * float(ratio),
                "effective_value": float(effective),
            })
        return tuple(rows)

    def rebase(
        self,
        *,
        thresholds: Mapping[str, float] | None = None,
        utility_weights: Mapping[str, float] | None = None,
        parameters: Mapping[str, float] | None = None,
        strategy_priors: Mapping[str, float] | None = None,
        risk_weight: float | None = None,
        version: int | None = None,
    ) -> "PolicyState":
        """在保留 Learned Overlay 比例的前提下替换 Base Config。

        主要用于测试、离线调参以及未来的持久化恢复流程。生产运行中 main3.py 会在
        Runtime 创建前一次性确定 Base Config，不会热修改 Base。
        """
        return PolicyState.create(
            version=self.version if version is None else int(version),
            thresholds=self.base_thresholds if thresholds is None else thresholds,
            utility_weights=self.base_utility_weights if utility_weights is None else utility_weights,
            parameters=self.base_parameters if parameters is None else parameters,
            strategy_priors=self.base_strategy_priors if strategy_priors is None else strategy_priors,
            risk_weight=self.base_risk_weight if risk_weight is None else float(risk_weight),
            learned_overlay=self.learned_overlay,
        )


@dataclass(frozen=True, slots=True)
class PolicyPatch:
    patch_id: str
    parent_version: int

    component: str
    key: str

    # Learner 仍以 Effective Config 表达提案。Repository 会把 new_value 自动换算为
    # 相对 Base 的 Learned Overlay，避免要求每个 learner 理解 overlay 细节。
    old_value: float | None
    new_value: float

    reason: str
    proposer: str
    confidence: float

    def validate(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")

        if self.component not in {
            "thresholds",
            "utility_weights",
            "parameters",
            "strategy_priors",
            "risk_weight",
        }:
            raise ValueError(
                f"unsupported patch component: {self.component}"
            )
