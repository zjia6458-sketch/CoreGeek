import asyncio
import json
from types import SimpleNamespace

from fortress_agent.server.http import HttpTurnService


class GoodRuntime:
    async def handle_turn(self, body):
        return SimpleNamespace(
            ok=True,
            response_json=(
                '{"roleCommandMap":{},'
                '"prompt":"","executeCmd":""}'
            ),
        )


class BadRuntime:
    async def handle_turn(self, body):
        raise RuntimeError("boom")


class SlowRuntime:
    async def handle_turn(self, body):
        await asyncio.sleep(0.05)
        return SimpleNamespace(
            ok=True,
            response_json="{}",
        )


def test_http_service_returns_runtime_json():
    response = HttpTurnService(
        GoodRuntime()
    ).handle(b"{}")

    assert response.status == 200
    assert json.loads(response.body)[
        "roleCommandMap"
    ] == {}


def test_http_service_converts_exception_to_safe_json():
    response = HttpTurnService(
        BadRuntime()
    ).handle(b"{}")

    payload = json.loads(response.body)

    assert response.status == 200
    assert payload == {
        "roleCommandMap": {},
        "prompt": "",
        "executeCmd": "",
    }


def test_http_service_converts_timeout_to_safe_json():
    response = HttpTurnService(
        SlowRuntime(),
        outer_timeout_seconds=0.001,
    ).handle(b"{}")

    assert response.status == 200
    assert json.loads(response.body)[
        "roleCommandMap"
    ] == {}


def test_http_service_rejects_oversized_body_with_valid_json():
    response = HttpTurnService(
        GoodRuntime(),
        max_request_bytes=2,
    ).handle(b"123")

    assert response.status == 413
    assert "roleCommandMap" in json.loads(
        response.body
    )


class BlockingRuntime:
    """故意使用 time.sleep 模拟完全不 await 的同步阻塞。"""

    def __init__(self):
        self.abandoned = []

    async def handle_turn(self, body):
        import time
        time.sleep(0.08)
        return SimpleNamespace(
            ok=True,
            response_json='{"roleCommandMap":{"1":{"action":"move","targetPos":[{"x":1,"y":1}]}},"prompt":"","executeCmd":""}',
            correlation_id="blocking-turn",
        )

    def abandon_undelivered_response(self, correlation_id):
        self.abandoned.append(correlation_id)

    def close(self):
        return


def test_http_outer_watchdog_handles_sync_blocking_runtime():
    import time

    runtime = BlockingRuntime()
    service = HttpTurnService(
        runtime,
        outer_timeout_seconds=0.005,
    )

    started = time.perf_counter()
    response = service.handle(b"{}")
    elapsed = time.perf_counter() - started

    # 关键验证：即使 Runtime 内部完全不 await，HTTP 也不能跟着 sleep 80ms。
    assert elapsed < 0.05
    assert json.loads(response.body)["roleCommandMap"] == {}

    # 上一 worker 尚未结束时，下一请求必须立即 busy-fallback，不能排队等待。
    started = time.perf_counter()
    second = service.handle(b"{}")
    second_elapsed = time.perf_counter() - started
    assert second_elapsed < 0.05
    assert json.loads(second.body)["roleCommandMap"] == {}

    time.sleep(0.10)
    assert runtime.abandoned == ["blocking-turn"]
    service.close()
