# FortressAgent V0.3.4 — Single Logger Observability

## 1. Production constraint

The judging environment exposes only one downloadable log stream: stdout from
the process launched through:

```bash
python main3.py <port>
```

Therefore production FortressAgent uses exactly one physical logging outlet.

`main3.py` is the **only** module allowed to configure logging:

```python
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
```

All framework modules use the same root logger:

```python
logging.getLogger()
```

They do **not** create:

```text
FileHandler
extra stdout handler
trace.jsonl
io.jsonl
experience.jsonl
world_events.jsonl
world_snapshot.json
```

in the production path.

---

## 2. One physical log, multiple logical channels

Every machine-readable runtime record is emitted as compact one-line JSON in
the `message` field.

Example:

```text
2026-09-18 19:00:00,000 | INFO | {"channel":"trace","record_type":"trace","event":{"kind":"strategy_selected",...}}
```

Logical channels:

```text
system       process/bootstrap information
io           request / response / parse errors
world_event  DomainEvent facts
trace        policy/strategy/team/final-validator execution
experience   ExperienceRecord / OutcomeRecord
```

Therefore only one log needs to be downloaded, while analysis can still filter:

```bash
grep '"channel":"experience"' competition.log
grep '"correlation_id":"r85:attempt:1"' competition.log
grep '"kind":"final_response_validated"' competition.log
```

---

## 3. Correlation chain

A turn keeps the existing correlation id:

```text
r85:attempt:1
```

The same id appears in:

```text
io request
world events
trace events
team decision trace
experience records
io response
```

When the next response arrives, Outcome records contain their own correlation id
and reference the previous decision/experience IDs, so the full causal loop can
be reconstructed from the single stdout log.

---

## 4. Production stores

The operational objects remain in memory:

```text
WorldMemory        in memory
EventStore         InMemoryEventStore
ExperienceStore    InMemoryExperienceStore
StrategicMemory    in memory
PolicyState        in memory
StrategySession    in memory
```

`JournaledEventStore` and `JournaledExperienceStore` are still used, but their
journal writer is now `LoggerJsonWriter`, so the journal destination is the
root logger rather than a file.

This means:

```text
state for decision making  -> memory
state for post-game audit  -> single stdout log
```

---

## 5. Why production snapshot files are disabled

A hidden `world_snapshot.json` that cannot be downloaded provides little
observability value and creates a second persistence dependency that differs
from the actual judging interface.

Production therefore sets:

```python
world_snapshot_store=None
```

The local/offline `build_logged_runtime()` remains available only for replay and
recovery development tests; `main3.py` never calls it.

If the competition later exposes a persistent/downloadable volume, snapshot
persistence can be re-enabled without changing the policy architecture.

---

## 6. Production entry chain

```text
python main3.py <port>
    ↓
main3.py
    ├── configure ONE root stdout logger
    └── agent.server.serve(port)
            ↓
       build_runtime(logger=root)
            ├── LoggerTraceSink
            ├── LoggerJsonWriter(channel=io)
            ├── LoggerJsonWriter(channel=world_event)
            └── LoggerJsonWriter(channel=experience)
            ↓
       run_http_server(...)
```

No production module calls `logging.basicConfig()` except `main3.py`.

---

## 7. Closed-loop log example

A single downloaded log can contain:

```json
{"channel":"io","record_type":"request","correlation_id":"r10:attempt:1",...}
{"channel":"world_event","event_type":"ResourceDiscovered","correlation_id":"r10:attempt:1",...}
{"channel":"trace","record_type":"trace","event":{"kind":"strategy_selected","correlation_id":"r10:attempt:1",...}}
{"channel":"trace","record_type":"trace","event":{"kind":"team_decision_planned","correlation_id":"r10:attempt:1",...}}
{"channel":"experience","record_type":"experience","experience":{"experience_id":"exp:r10:attempt:1:...",...}}
{"channel":"io","record_type":"response","correlation_id":"r10:attempt:1",...}
```

On round 11:

```json
{"channel":"experience","record_type":"outcome","outcome":{"outcome_id":"outcome:...:11","action_legal":true,...}}
```

This is sufficient to reconstruct:

```text
server request
→ world update
→ strategy
→ candidate/ranking
→ team action
→ actual response
→ next-round legality/reward
→ experience outcome
```

using one physical log only.
