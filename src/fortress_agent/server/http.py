from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading

from fortress_agent.application.runtime import FortressAgentRuntime
from fortress_agent.protocol.codec import GameProtocolCodec
from fortress_agent.protocol.server_outbound import ServerCommandResponse
from fortress_agent.observability.logger import LogMode


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """HTTP 层内部响应对象。

    ``correlation_id`` 不会写入 wire JSON，只用于在 BrokenPipe 时通知 Runtime：
    该回合虽然完成了决策，但响应实际上没有送达判题器。
    """

    status: int
    body: str
    content_type: str = "application/json; charset=utf-8"
    correlation_id: str | None = None


class HttpTurnService:
    """将 HTTP 请求转换为单回合 Runtime 调用，并提供真正的外层 watchdog。

    为什么不能只用 ``asyncio.wait_for``：
    Runtime 内存在大量同步 CPU 逻辑（A*、候选生成、排序、校验）。如果某段同步
    代码长时间不 ``await``，事件循环无法及时执行取消，wait_for 就不能保证墙钟
    时间小于 5 秒。

    因此这里使用一个 ``ThreadPoolExecutor(max_workers=1)``：
    - HTTP handler 线程只等待 ``outer_timeout_seconds``；
    - 超时后立即返回合法空响应，不等待计算线程；
    - 单 worker 保证 Runtime 的有状态 Memory/Experience 不会并发修改；
    - 上一回合若仍在拖尾，下一请求直接 busy-fallback，不在锁上排队。

    正常情况下 Runtime 自己会在更早的 internal deadline（默认 3.2s）主动结束，
    executor watchdog 只是最后一道保险。
    """

    def __init__(
        self,
        runtime: FortressAgentRuntime | None = None,
        *,
        outer_timeout_seconds: float = 4.2,
        max_request_bytes: int = 2 * 1024 * 1024,
        logger: logging.Logger | None = None,
        log_mode: LogMode | str = LogMode.MEDIUM,
    ) -> None:
        self._runtime = runtime or FortressAgentRuntime()
        self._outer_timeout = max(0.001, float(outer_timeout_seconds))
        self._max_request_bytes = max_request_bytes
        self._codec = GameProtocolCodec()
        self._logger = logger or logging.getLogger()
        self._log_mode = LogMode.parse(log_mode)

        # Runtime 是有状态对象，严格限制为一个 worker。_busy 表示该 worker 当前
        # 是否仍在处理上一回合，避免 ThreadingHTTPServer 把后续请求排队到超时。
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="fortress-turn",
        )
        self._busy = threading.Lock()
        self._closed = False

    def handle(self, body: bytes) -> HttpResponse:
        if len(body) > self._max_request_bytes:
            return HttpResponse(
                status=413,
                body=self._safe_empty_response(),
            )

        # 正常协议不会并发发两个回合。若这里 busy，通常意味着上一回合已经拖过
        # 客户端等待窗口。此时立即空响应比“等锁 -> 再超时一次”安全得多。
        if not self._busy.acquire(blocking=False):
            self._log_event(
                "request_busy_fallback",
                outer_timeout_seconds=self._outer_timeout,
            )
            return HttpResponse(
                status=200,
                body=self._safe_empty_response(),
            )

        try:
            future = self._executor.submit(
                self._run_runtime,
                body,
            )
        except Exception as exc:
            self._busy.release()
            self._log_event(
                "turn_submit_failed",
                error=repr(exc),
            )
            return HttpResponse(
                status=200,
                body=self._safe_empty_response(),
            )

        try:
            result = future.result(
                timeout=self._outer_timeout
            )
        except FutureTimeoutError:
            # 不能 cancel 正在运行的 Python thread。让它自然结束，但 busy 锁继续
            # 保持；结束回调会撤销未送达动作并释放 busy。
            future.add_done_callback(
                self._finish_timed_out_future
            )
            self._log_event(
                "http_outer_timeout_fallback",
                outer_timeout_seconds=self._outer_timeout,
            )
            return HttpResponse(
                status=200,
                body=self._safe_empty_response(),
            )
        except Exception as exc:
            self._busy.release()
            self._log_event(
                "runtime_exception_fallback",
                error=repr(exc),
            )
            return HttpResponse(
                status=200,
                body=self._safe_empty_response(),
            )

        self._busy.release()

        if not result.ok or result.response_json is None:
            return HttpResponse(
                status=200,
                body=self._safe_empty_response(),
                correlation_id=getattr(result, "correlation_id", None),
            )

        return HttpResponse(
            status=200,
            body=result.response_json,
            correlation_id=getattr(result, "correlation_id", None),
        )

    def mark_not_delivered(
        self,
        correlation_id: str | None,
        *,
        reason: str,
    ) -> None:
        """通知 Runtime：已经生成的响应没有真正送达客户端。"""

        abandon = getattr(
            self._runtime,
            "abandon_undelivered_response",
            None,
        )
        if abandon is not None:
            abandon(correlation_id)
        self._log_event(
            "response_not_delivered",
            correlation_id=correlation_id,
            reason=reason,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(
            wait=False,
            cancel_futures=True,
        )
        close = getattr(self._runtime, "close", None)
        if close is not None:
            close()

    def _run_runtime(self, body: bytes):
        # 每个请求在独立 worker thread 中创建自己的 asyncio event loop。
        return asyncio.run(self._runtime.handle_turn(body))

    def _finish_timed_out_future(self, future: Future) -> None:
        """拖尾任务结束后的清理回调。

        外层已经给判题器回了安全空响应，所以原 Runtime 结果中的动作绝不能在
        下一回合继续作为 pending experience 使用。
        """

        try:
            result = future.result()
        except Exception as exc:
            self._log_event(
                "timed_out_worker_finished_with_error",
                error=repr(exc),
            )
        else:
            abandon = getattr(
                self._runtime,
                "abandon_undelivered_response",
                None,
            )
            correlation_id = getattr(result, "correlation_id", None)
            if abandon is not None:
                abandon(correlation_id)
            self._log_event(
                "timed_out_worker_discarded",
                correlation_id=correlation_id,
            )
        finally:
            try:
                self._busy.release()
            except RuntimeError:
                pass

    def _safe_empty_response(self) -> str:
        result = self._codec.serialize_server_response(
            ServerCommandResponse()
        )
        return (
            result.value
            if result.ok and result.value is not None
            else '{"roleCommandMap":{},"prompt":"","executeCmd":""}'
        )

    def _log_event(self, event: str, **data: object) -> None:
        """HIGH 模式下输出 HTTP 安全事件；LOW/MEDIUM 保持回合日志纯净。"""

        if self._log_mode is not LogMode.HIGH:
            return
        try:
            payload = {
                "channel": "system",
                "event": event,
                **data,
            }
            self._logger.info(
                "%s",
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        except Exception:
            # 可观测性永远不能破坏决策/响应路径。
            pass


class FortressRequestHandler(BaseHTTPRequestHandler):
    """比赛 HTTP handler。

    仅负责读取 body、调用 HttpTurnService、写回 JSON。业务逻辑全部位于 Runtime。
    """

    service: HttpTurnService

    def do_POST(self) -> None:
        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )
        except ValueError:
            content_length = 0

        body = self.rfile.read(
            max(0, content_length)
        )

        response = self.service.handle(body)
        encoded = response.body.encode("utf-8")

        try:
            self.send_response(response.status)
            self.send_header(
                "Content-Type",
                response.content_type,
            )
            self.send_header(
                "Content-Length",
                str(len(encoded)),
            )
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            # 典型场景：判题器已经在 5 秒超时后关闭 socket。这个异常是结果，
            # 不是根因；必须吞掉，避免 socketserver 打出整段未处理 Traceback。
            self.service.mark_not_delivered(
                response.correlation_id,
                reason=f"{type(exc).__name__}:{exc}",
            )
            return

    def do_GET(self) -> None:
        if self.path in {"/health", "/healthz"}:
            payload = b'{"status":"ok"}'
            try:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json",
                )
                self.send_header(
                    "Content-Length",
                    str(len(payload)),
                )
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return

        try:
            self.send_response(404)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def log_message(
        self,
        format: str,
        *args,
    ) -> None:
        # 禁止 BaseHTTPRequestHandler 自己向 stdout/stderr 打非结构化访问日志。
        return


class CompetitionThreadingHTTPServer(ThreadingHTTPServer):
    """比赛专用 ThreadingHTTPServer。

    handler 可以并发接收连接，但真正的有状态 Runtime 由 HttpTurnService 的单 worker
    串行执行。daemon thread 避免进程退出时被失联客户端阻塞。
    """

    daemon_threads = True
    block_on_close = False


def run_http_server(
    port: int,
    *,
    host: str = "0.0.0.0",
    runtime: FortressAgentRuntime | None = None,
    outer_timeout_seconds: float = 4.2,
    logger: logging.Logger | None = None,
    log_mode: LogMode | str = LogMode.MEDIUM,
) -> None:
    service = HttpTurnService(
        runtime,
        outer_timeout_seconds=outer_timeout_seconds,
        logger=logger,
        log_mode=log_mode,
    )

    handler = type(
        "BoundFortressRequestHandler",
        (FortressRequestHandler,),
        {"service": service},
    )

    server = CompetitionThreadingHTTPServer(
        (host, port),
        handler,
    )

    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.close()
