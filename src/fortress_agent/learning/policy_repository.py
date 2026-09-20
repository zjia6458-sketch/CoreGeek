from __future__ import annotations

from fortress_agent.domain.policy_state import (
    PolicyPatch,
    PolicyState,
)


class InMemoryPolicyStateRepository:
    """内存策略仓库：Base Config 固定，学习只维护 Relative Learned Overlay。

    ``PolicyPatch`` 中的 ``new_value`` 仍表示 learner 想要的 Effective 值；仓库在
    创建候选时将它转换为 ``new_value / base_value - 1``，并只把该比例写入
    ``PolicyState.learned_overlay``。因此未来 Base 从 4 改成 8 时，+5% 的学习结果
    会自然从 +0.2 缩放成 +0.4。

    当前仓库完全驻留内存，不读写 JSONL；程序重启后从 main3.py 的 Base Config
    重新开始学习。
    """

    def __init__(
        self,
        initial: PolicyState | None = None,
    ) -> None:
        initial = initial or PolicyState.create()

        self._states: dict[int, PolicyState] = {
            initial.version: initial
        }
        self._current_version = initial.version
        self._parent: dict[int, int | None] = {
            initial.version: None
        }
        self._patch: dict[int, PolicyPatch | None] = {
            initial.version: None
        }

    def current(self) -> PolicyState:
        return self._states[self._current_version]

    def get(self, version: int) -> PolicyState:
        return self._states[version]

    def create_candidate(
        self,
        patch: PolicyPatch,
    ) -> PolicyState:
        patch.validate()

        if patch.parent_version not in self._states:
            raise KeyError(
                f"unknown parent version: {patch.parent_version}"
            )

        parent = self._states[patch.parent_version]

        if patch.parent_version != self._current_version:
            # 第一版仍禁止从 stale policy 分叉，保持学习链线性、便于复盘。
            raise ValueError(
                "candidate must be created from current policy"
            )

        base_value = parent.base_value(patch.component, patch.key)
        if base_value is None:
            raise KeyError(
                f"unknown base policy parameter: {patch.component}.{patch.key}"
            )
        if abs(base_value) < 1e-12:
            # 相对 Overlay 对零基线没有稳定含义。此类参数如需学习，应先给非零 Base，
            # 或未来单独设计 additive overlay；当前直接拒绝，避免隐藏绝对值语义。
            raise ValueError(
                f"relative learned overlay requires non-zero base value: "
                f"{patch.component}.{patch.key}"
            )

        relative_overlay = float(patch.new_value) / float(base_value) - 1.0
        learned_overlay = dict(parent.learned_overlay)
        path = (
            "risk_weight"
            if patch.component == "risk_weight"
            else f"{patch.component}.{patch.key}"
        )
        if abs(relative_overlay) < 1e-12:
            learned_overlay.pop(path, None)
        else:
            learned_overlay[path] = relative_overlay

        next_version = max(self._states) + 1
        candidate = PolicyState.create(
            version=next_version,
            thresholds=parent.base_thresholds,
            utility_weights=parent.base_utility_weights,
            parameters=parent.base_parameters,
            strategy_priors=parent.base_strategy_priors,
            risk_weight=parent.base_risk_weight,
            learned_overlay=learned_overlay,
        )

        self._states[next_version] = candidate
        self._parent[next_version] = parent.version
        self._patch[next_version] = patch

        return candidate

    def promote(self, version: int) -> None:
        if version not in self._states:
            raise KeyError(f"unknown version: {version}")
        self._current_version = version

    def rollback(self, version: int) -> None:
        if version not in self._states:
            raise KeyError(f"unknown version: {version}")
        self._current_version = version

    def parent_version(
        self,
        version: int,
    ) -> int | None:
        return self._parent[version]

    def patch_for(
        self,
        version: int,
    ) -> PolicyPatch | None:
        return self._patch[version]

    def learned_overlay_snapshot(self) -> tuple[dict[str, float | str], ...]:
        return self.current().overlay_snapshot()
