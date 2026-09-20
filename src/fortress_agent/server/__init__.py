from .http import HttpResponse, HttpTurnService, run_http_server


def serve(port: int) -> None:
    """Internal convenience alias using the default runtime."""
    run_http_server(port, host="0.0.0.0")


__all__ = [
    "HttpResponse",
    "HttpTurnService",
    "run_http_server",
    "serve",
]
