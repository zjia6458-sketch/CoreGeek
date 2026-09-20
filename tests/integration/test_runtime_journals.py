import asyncio
import json

from fortress_agent.application.bootstrap import build_logged_runtime


def request(round_no, *, include_resource, llm_resp="", role_results=None, score=0, backpack=None):
    zones = [
        {"neutralType": "stone", "pos": {"x": 5, "y": 5}},
    ] if include_resource else []

    return {
        "roundNo": round_no,
        "mapInfo": {"width": 41, "height": 32, "zones": zones},
        "teamOur": {
            "type": "challenger",
            "teamId": "demo",
            "teamName": "Demo",
            "goldNum": 0,
            "totalScore": score,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 5, "y": 5},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": backpack or [],
                },
                {
                    "id": 10011,
                    "pos": {"x": 10, "y": 12},
                    "roleType": "pioneer",
                    "health": 200,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 40,
                    "backpack": [],
                },
            ],
        },
        "teamEnemy": {"roles": []},
        "robot": {"roles": []},
        "lastRoundRoleActionResults": role_results or {},
        "llmResp": llm_resp,
        "worldNews": {
            "officialNews": "",
            "folkLegends": "西部有一石门，门需三钥",
        },
        "vendorShopList": [{"name": "stone", "price": 1}],
        "weaponShopList": [],
        "errors": [],
    }


def test_logged_runtime_persists_correlated_closed_loop(tmp_path):
    runtime = build_logged_runtime(tmp_path)

    first = asyncio.run(runtime.handle_turn(request(10, include_resource=True)))
    assert first.ok

    advisory = json.dumps({
        "schema_version": "1.0",
        "source_round": 10,
        "recommended_mode": "explore",
        "mode_strength": 0.8,
        "confidence": 0.7,
        "expires_after_rounds": 130,
        "claims": [],
        "objectives": [],
        "short_reason": "structured demo advisory",
    }, ensure_ascii=False)

    second = asyncio.run(runtime.handle_turn(request(
        11,
        include_resource=False,
        llm_resp=advisory,
        role_results={"10010": True, "10011": True},
        score=2,
        backpack=["stone"],
    )))
    assert second.ok

    runtime.close()

    trace_rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    event_rows = [json.loads(line) for line in (tmp_path / "world_events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    exp_rows = [json.loads(line) for line in (tmp_path / "experience.jsonl").read_text(encoding="utf-8").splitlines() if line]
    io_rows = [json.loads(line) for line in (tmp_path / "io.jsonl").read_text(encoding="utf-8").splitlines() if line]

    assert any(row["kind"] == "policy_node_completed" and row["correlation_id"] == first.correlation_id for row in trace_rows)
    assert any(row["kind"] == "outcome_attached" and row["correlation_id"] == second.correlation_id for row in trace_rows)
    assert any(row["event_type"] == "ResourceDiscovered" and row["payload"]["correlation_id"] == first.correlation_id for row in event_rows)
    assert any(row["event_type"] == "ResourceDepleted" and row["payload"]["correlation_id"] == second.correlation_id for row in event_rows)
    assert any(row["record_type"] == "experience" and row["experience"]["correlation_id"] == first.correlation_id for row in exp_rows)
    assert any(row["record_type"] == "outcome" and row["outcome"]["correlation_id"] == second.correlation_id for row in exp_rows)
    assert [row["record_type"] for row in io_rows].count("request") == 2
    assert [row["record_type"] for row in io_rows].count("response") == 2
