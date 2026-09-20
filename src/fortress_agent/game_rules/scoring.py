from __future__ import annotations


def completed_task_score(
    *,
    task_score_reward: float,
    timeout_rounds: int,
    accepted_round: int,
    completed_round: int,
) -> float:
    elapsed = completed_round - accepted_round
    if elapsed <= 0:
        return float(task_score_reward)
    return float(task_score_reward) + 5.0 * float(timeout_rounds) / float(elapsed)


def partial_task_score(*, task_score_reward: float, pass_rate: float) -> float:
    bounded = min(1.0, max(0.0, float(pass_rate)))
    return float(task_score_reward) * bounded


def survival_day_score(*, day: int, base_alive: bool) -> float:
    return float(10 * int(day)) if base_alive else 0.0


def kill_score(score_values: list[int] | tuple[int, ...]) -> int:
    return sum(int(v) for v in score_values)
