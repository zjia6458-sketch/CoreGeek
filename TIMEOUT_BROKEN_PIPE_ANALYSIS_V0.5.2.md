# FortressAgent V0.5.2：TIMEOUT / BrokenPipe 问题分析与修复

## 1. 结论

日志中的核心故障不是 `BrokenPipeError` 本身，而是**上一回合 HTTP 请求已经超过判题器 5 秒等待上限**。

判题器先记录：

```text
[1,"com.hw.codecraft.engine.exceptions.JudgeException: [TIMEOUT] player(4737) request timeout"]
```

并关闭对应 TCP 连接；我们的服务器线程稍后才完成计算，继续执行：

```python
self.wfile.write(encoded)
```

此时客户端 socket 已经不存在，所以 Python 抛出：

```text
BrokenPipeError: [Errno 32] Broken pipe
```

因此故障顺序是：

```text
决策耗时过长
    ↓
判题器 5 秒超时
    ↓
判题器关闭连接
    ↓
我们的旧线程稍后完成
    ↓
wfile.write()
    ↓
BrokenPipeError
```

`BrokenPipeError` 是**结果**，不是导致 5 秒超时的原因。

---

## 2. 从日志逐行解释

### 2.1 判题器已经认定上一请求超时

Round 25 收到：

```json
{
  "kind":"server_feedback_observed",
  "round_id":25,
  "data":{
    "role_action_results":{},
    "last_summon_treasure_result":0,
    "last_command_result":"",
    "server_errors":[
      [1,"com.hw.codecraft.engine.exceptions.JudgeException: [TIMEOUT] player(4737) request timeout"]
    ]
  }
}
```

这里最重要的是：

```text
role_action_results = {}
```

并且错误明确写着：

```text
request timeout
```

这说明上一回合不是某个 MOVE/BUILD/ATTACK 执行失败，而是**整个 HTTP 响应没有按时交付**。

### 2.2 旧实现错误地把 TIMEOUT 传播到每个角色 Experience

旧日志随后出现三条：

```text
outcome:r24...20010:move
outcome:r24...20011:move
outcome:r24...20012:move
```

且都有：

```json
"action_legal": null,
"server_error_codes": [1],
"reward_total": 0.0
```

这个语义不严谨。

因为若上一 HTTP Response 根本没送达判题器，则这三个动作不应被解释为：

> “动作已经发送，只是执行是否合法未知。”

更准确的含义是：

> “上一回合 Response Delivery 失败，不能对动作做 Outcome 归因。”

V0.5.2 因此新增：

```text
previous_response_timeout_observed
```

并在检测到收到的 `server_errors[].description` 明确属于 `request timeout` 时：

1. 清空上一轮 `pending_experiences`；
2. 不给上一回合各角色动作绑定 Outcome；
3. 不让 OnlineLearner 从网络/响应超时错误学习动作价值；
4. 保留一个统一的 ResponseAnomaly trace 供人工分析。

---

## 3. 为什么旧 `asyncio.wait_for(4.6s)` 没能阻止 5 秒超时

旧 HTTP 代码本来已经有：

```python
asyncio.wait_for(
    self._runtime.handle_turn(body),
    timeout=4.6,
)
```

乍看应该在 4.6 秒结束，但这里存在 Python asyncio 的重要限制。

`handle_turn()` 虽然是 `async def`，内部大量逻辑其实是同步 CPU 工作，例如：

- Candidate generation；
- A* pathfinding；
- Reward/Evaluator 排序；
- TeamPlanner；
- Final validation；
- Memory projection；
- structured logging。

如果一个 async coroutine 长时间执行同步代码、期间没有真正 `await` 一个会 suspend 的操作，Event Loop 就没有机会处理 timeout cancellation。

因此：

```text
asyncio.wait_for != 对同步 CPU 代码的强制墙钟中断器
```

V0.5.2 做了两层修复。

---

## 4. V0.5.2 的两层 Deadline 体系

### 4.1 内部 Deadline：3.2 秒

`main3.py`：

```python
INTERNAL_DEADLINE_SECONDS = 3.2
```

Runtime 的目标不是用满判题器的 5 秒，而是在约 3.2 秒内完成复杂决策或主动降级。

剩余时间给：

- Response JSON serialization；
- Thread scheduling；
- HTTP header；
- TCP socket write；
- 容器/判题器之间的抖动。

Runtime 在关键阶段检查剩余预算：

```text
Parse / Feedback / Memory
    ↓
预算不足 → safe empty response
    ↓
PolicyGraph
    ↓
预算不足 → safe empty response
    ↓
TeamPlanner
    ↓
预算不足 → safe empty response
    ↓
Encoder / FinalValidator
    ↓
Experience commit
```

降级响应始终是协议合法的：

```json
{
  "roleCommandMap": {},
  "prompt": "",
  "executeCmd": ""
}
```

这意味着：

> 宁可这一回合不动作，也不把整队的一次异常额度消耗在超时上。

### 4.2 HTTP Outer Watchdog：4.2 秒

`main3.py`：

```python
HTTP_OUTER_TIMEOUT_SECONDS = 4.2
```

新的 `HttpTurnService` 不再依赖 `asyncio.wait_for` 作为最后保险，而是把 Runtime 放入：

```python
ThreadPoolExecutor(max_workers=1)
```

HTTP handler 只等待：

```python
future.result(timeout=4.2)
```

即使 Runtime 内部某段代码发生完全同步阻塞，没有任何 `await`，HTTP handler 也能在 4.2 秒左右结束等待并返回 safe empty response。

---

## 5. 为什么只允许一个 Runtime worker

FortressAgent 的 Runtime 是有状态的，内部包含：

- WorldMemory；
- RuntimeFeedbackMemory；
- StrategicMemory；
- pending Experience；
- PolicyRepository；
- LLM budget。

因此不能让两个 HTTP thread 同时调用：

```python
runtime.handle_turn(...)
```

V0.5.2 使用：

```text
ThreadingHTTPServer
    ↓
多个 connection handler 可以存在
    ↓
HttpTurnService
    ↓
单 worker Runtime executor
```

如果上一回合已经超时但后台 worker 尚未自然结束，下一请求不会继续等待 worker：

```text
busy = true
    ↓
立即返回 safe empty response
```

对应日志：

```text
request_busy_fallback
```

目的就是避免：

```text
Round 24 超时
    ↓
Round 25 等 Round 24 的 lock
    ↓
Round 25 再超时
    ↓
Round 26 再等待
```

形成超时雪崩。

---

## 6. BrokenPipe 的处理

旧代码：

```python
self.wfile.write(encoded)
```

没有 catch，导致 `socketserver` 输出整段：

```text
Exception occurred during processing of request ...
Traceback ...
BrokenPipeError
```

V0.5.2 现在捕获：

```python
BrokenPipeError
ConnectionResetError
ConnectionAbortedError
OSError
```

不会再向 stdout/stderr 打未处理 Traceback，而会通过唯一 root logger 输出结构化事件：

```json
{
  "channel":"system",
  "event":"response_not_delivered",
  "correlation_id":"...",
  "reason":"BrokenPipeError:..."
}
```

同时调用：

```python
runtime.abandon_undelivered_response(correlation_id)
```

清除该 Response 对应的 pending Experience，避免下一回合错误归因。

---

## 7. 两个主要性能热点的修复

### 7.1 `find_path_to_any()` 从 N 次 A* 改为一次 Multi-goal A*

旧逻辑：

```text
resource access cell 1 → 跑 A*
resource access cell 2 → 再跑 A*
...
resource access cell 8 → 再跑 A*
```

如果：

```text
2 Workers × 12 Resources × 8 access cells
```

理论上可能触发大量重复地图搜索。

新逻辑：

```text
所有 access cells
    ↓
一个 goal set
    ↓
一次 A*
    ↓
命中任意最优 goal 即结束
```

启发函数使用：

```text
min(ChebyshevDistance(current, goal_i))
```

同时增加：

- `max_expansions`；
- 每 32 次展开检查 Deadline；
- Deadline reserve。

### 7.2 TeamPlanner 不再重复生成 Candidate

旧数据流：

```text
PolicyGraph
  Candidate → Legal → Rule → Rank

然后 TeamPlanner 又执行：
  Candidate → Legal → Rule → 每角色 Rank
```

最重的 Pathfinding 被重复做两遍。

V0.5.2 改为：

```text
PolicyGraph
  Candidate → Legal → Rule
                ↓
        frame.viable_actions
                ↓
TeamPlanner.plan_from_viable()
                ↓
按 actor 分组 Rank
                ↓
TeamConstraint
```

Candidate/Legal/Rule 现在一回合只计算一次。

---

## 8. 夜间组合爆炸保护

Gatling level3 可以选择多个目标。如果场上机器人很多，直接：

```python
combinations(targets, 3)
```

可能快速膨胀。

V0.5.2 增加：

```text
max_target_pool = 12
max_target_sets = 32
```

先按威胁/积分排序，只在高价值目标池内组合；几何合法性和 FinalValidator 仍保留，因此只是降低搜索宽度，不降低协议安全性。

---

## 9. 新增的关键日志

### Deadline 主动降级

```text
deadline_fallback
```

包含：

```text
reason
elapsed_seconds
remaining_seconds
response=safe_empty
```

### HTTP 外层强制降级

```text
http_outer_timeout_fallback
```

### 上一 worker 未结束时快速降级

```text
request_busy_fallback
```

### 判题器报告上一请求超时

```text
previous_response_timeout_observed
```

### Response 生成后客户端已断开

```text
response_not_delivered
response_delivery_abandoned
```

这些事件使后续日志能够区分：

```text
策略执行慢
HTTP watchdog
客户端断开
动作执行失败
协议异常
```

不再全部混成 `action_legal=false`。

---

## 10. 推荐关注指标

比赛日志中建议重点搜索：

```text
turn_completed
```

看：

```text
deadline_remaining
```

以及：

```text
deadline_fallback
http_outer_timeout_fallback
request_busy_fallback
previous_response_timeout_observed
response_not_delivered
```

如果大量 `turn_completed` 的 `deadline_remaining` 已经低于 1 秒，应优先做算法性能优化，而不是继续缩短 HTTP timeout。

---

## 11. 安全边界

V0.5.2 的目标不是保证每回合都有动作，而是保证：

```text
合法响应 > 高收益动作
```

因为比赛明确规定一次队伍最多只有有限异常机会。一个保守空响应只损失一个回合的行动机会；一个 HTTP timeout 可能直接消耗异常额度并引发后续级联。
