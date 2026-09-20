# FortressAgent V0.5.8 文本任务 Prompt 优化

## 1. 快速定位 Prompt

在源码中搜索：

```text
# todo(TEXT_TASK_PROMPT)
```

主要入口：

```text
src/fortress_agent/tasks/session.py
TaskSessionCoordinator._build_prompt()
```

这里是任务 Prompt 的唯一主要编辑入口，避免把提示词散落到 Runtime / HTTP 层。

## 2. 本次问题

旧 Prompt 虽为中文，但工作流明显偏向 `executeCmd`：读取说明、执行命令、修复、再次执行。这适合 API/脚本类任务，却会误导纯文本理解任务进行无意义的文件探索，浪费回合，并增加最终答案漏字段或格式不符的概率。

## 3. 新流程

任务首先判断为 `text / tool / mixed` 三种模式。该分类只是提示，不是强制规则。

### 文本类

```text
读取 phaseTask / 已有 lastCmdResult
→ 明确问题与输出格式
→ 检查证据是否充分
→ 充分：立即 submit
→ 不充分且明确引用本地材料：最小 executeCmd 获取缺失材料
→ 再检查完整性和格式
→ submit
```

### 工具类

```text
读任务/文档
→ 一条最小验证命令
→ 根据 lastCmdResult 只修当前失败点
→ 验证
→ submit
```

### 混合类

先获取必要材料，再回到文本推理，不允许无限 shell 探索。

## 4. Submit 前强制检查

Prompt 明确要求检查：目标、证据、字段完整性、输出格式、实体/数字/大小写/单位精确性，并要求真正答案必须放在 `task_answer`，不能只写在 `short_reason`。

## 5. 容错

解析器仍严格验证 `task-1.0` schema，但允许模型在 JSON 前偶尔多输出一句中文说明：系统会提取第一个合法 JSON 对象再进行 Pydantic 严格校验。

## 6. 纯文本任务首回合

明显的纯文本任务不再默认执行 `find /tmp/selfEvolutionTask`。Prompt 直接交给任务 LLM；信息足够时下一回合即可 submit。API/文件/脚本任务仍保留 sandbox 文件发现 fallback。
