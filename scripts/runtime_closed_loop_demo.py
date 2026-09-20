from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil

from fortress_agent.application.bootstrap import build_logged_runtime


def make_request(round_no: int, *, resource: bool, score: int, backpack, role_results=None, llm_resp=""):
    return {
        "roundNo": round_no,
        "mapInfo": {
            "width": 41,
            "height": 32,
            "zones": ([{"neutralType": "stone", "pos": {"x": 5, "y": 5}}] if resource else []),
        },
        "teamOur": {
            "type": "challenger",
            "teamId": "demo-team",
            "teamName": "RuntimeDemo",
            "goldNum": 0,
            "totalScore": score,
            "playerTasks": [],
            "roles": [
                {
                    "id": 10010,
                    "pos": {"x": 5, "y": 4},
                    "roleType": "worker",
                    "health": 220,
                    "attackPower": 0,
                    "attackRange": 0,
                    "backPackCapability": 100,
                    "backpack": backpack,
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
        "lastSummonTreasureResult": 0,
        "llmResp": llm_resp,
        "worldNews": {
            "officialNews": "今日无重大新闻",
            "folkLegends": "西部有一石门，门需三钥",
        },
        "lastCmdResult": "",
        "vendorShopList": [{"name": "stone", "price": 1}],
        "weaponShopList": [],
        "errors": [],
    }


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="demo_runtime_logs")
    args = parser.parse_args()

    out = Path(args.output)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    runtime = build_logged_runtime(out)

    round10 = make_request(10, resource=True, score=0, backpack=[])
    result10 = asyncio.run(runtime.handle_turn(round10))

    advisory = json.dumps({
        "schema_version": "1.0",
        "source_round": 10,
        "recommended_mode": "explore",
        "mode_strength": 0.8,
        "confidence": 0.7,
        "expires_after_rounds": 130,
        "claims": [
            {
                "kind": "location_hint",
                "subject": "stone gate",
                "relation": "located_in",
                "object": "west",
                "confidence": 0.6,
            },
            {
                "kind": "requirement",
                "subject": "stone gate",
                "relation": "requires",
                "object": "three keys",
                "confidence": 0.6,
            },
        ],
        "objectives": [
            {
                "objective_type": "explore_region",
                "priority": 0.8,
                "description": "investigate western region",
                "target_position": None,
                "target_region": "west",
                "required_items": [],
            }
        ],
        "short_reason": "folk legend suggests a western gated location",
    }, ensure_ascii=False)

    round11 = make_request(
        11,
        resource=False,
        score=2,
        backpack=["stone"],
        role_results={"10010": True, "10011": True},
        llm_resp=advisory,
    )
    result11 = asyncio.run(runtime.handle_turn(round11))

    runtime.close()

    trace = read_jsonl(out / "trace.jsonl")
    events = read_jsonl(out / "world_events.jsonl")
    experiences = read_jsonl(out / "experience.jsonl")
    io = read_jsonl(out / "io.jsonl")

    summary = {
        "round10": {
            "correlation_id": result10.correlation_id,
            "response": json.loads(result10.response_json),
        },
        "round11": {
            "correlation_id": result11.correlation_id,
            "response": json.loads(result11.response_json),
            "realized_reward": (
                None if result11.realized_reward is None else result11.realized_reward.total
            ),
        },
        "trace_kinds_round10": [row["kind"] for row in trace if row.get("correlation_id") == result10.correlation_id],
        "trace_kinds_round11": [row["kind"] for row in trace if row.get("correlation_id") == result11.correlation_id],
        "world_events": [
            {
                "type": row["event_type"],
                "round": row["payload"]["round_id"],
                "correlation_id": row["payload"].get("correlation_id"),
            }
            for row in events
        ],
        "experience_records": [
            {
                "type": row["record_type"],
                "experience_id": row.get("experience", {}).get("experience_id"),
                "outcome_id": row.get("outcome", {}).get("outcome_id"),
                "correlation_id": (
                    row.get("experience", {}).get("correlation_id")
                    or row.get("outcome", {}).get("correlation_id")
                ),
            }
            for row in experiences
        ],
        "io_record_types": [row["record_type"] for row in io],
    }

    summary_path = out / "demo_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
