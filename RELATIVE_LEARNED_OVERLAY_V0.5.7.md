# FortressAgent V0.5.7：Base Config + Relative Learned Overlay

## 1. 设计目标

运行时学习不再直接改写人工配置，也不保存绝对增量。策略状态明确拆成三层：

```text
Base Config
    × (1 + Relative Learned Overlay)
    = Effective Config
```

例如 Base=4，学习希望 Effective=4.2：

```text
relative_overlay = 4.2 / 4 - 1 = +5%
```

以后人工把 Base 改成 8，同一个 +5% Overlay 对应：

```text
overlay_absolute = 8 × 5% = 0.4
effective = 8.4
```

因此历史学习表达的是“相对人工基线偏多少”，而不是“把参数强行写成某个旧绝对值”。

## 2. 代码结构

`domain/policy_state.py`：

- `base_thresholds/base_parameters/base_utility_weights/...`：人工基线；
- `learned_overlay`：`component.key -> relative ratio`；
- `thresholds/parameters/utility_weights/...`：运行时 Effective；
- `overlay_snapshot()`：生成 logger 所需的完整学习快照；
- `rebase()`：用于验证同一个 Overlay 在不同 Base 上按比例缩放。

`learning/policy_repository.py`：Learner 仍提出 Effective 值，Repository 将其换算成相对 Base 的比例后保存。

## 3. 运行时学习

Learner 接口保持不变。例如提案 `20 -> 10`，Runtime 先按小步规则夹紧成 `20 -> 19`，随后 Repository 记录：

```text
Base = 20
Effective = 19
Relative Overlay = -5%
Absolute Overlay = -1
```

如果未来 Base 人工改成 40，同一 -5% 的含义自动变成：

```text
Absolute Overlay = -2
Effective = 38
```

零基线参数当前禁止相对学习，因为 `0 × (1+r)` 无法表达有效增量。需要学习的软参数必须提供非零 Base。

## 4. 日志

LOW / MEDIUM / HIGH 的人类回合块都会在 `=====END=======` 前输出当前完整 Overlay：

```text
LearningUpdate: v2 thresholds.prepare_margin_rounds 20.000->19.000 overlay=-5.00%
...
LearnedOverlay:
  thresholds.prepare_margin_rounds: -5.00% (base=20.000, overlay=-1.000, effective=19.000)
=====END=======
```

即使该回合没有发生新学习，也会打印当前 Overlay；没有任何学习时显示：

```text
LearnedOverlay: none
```

比赛环境只有 stdout 可下载，因此 logger 是当前学习状态的审计来源。

## 5. 持久化

V0.5.7 **不启用 JSONL 或其它学习参数持久化**。进程重启后从 Base Config + 空 Overlay 启动。未来若恢复持久化，应保存 `relative_overlay` 百分比，而不是 Effective 值或绝对 delta。
