from __future__ import annotations

import json
from typing import Mapping, Protocol

from .journal import to_jsonable


class JournalWriter(Protocol):
    def write(
        self,
        payload: Mapping[str, object],
    ) -> None:
        ...

    def close(self) -> None:
        ...


class IoJournal:
    def __init__(
        self,
        writer: JournalWriter,
    ) -> None:
        self._writer = writer

    def record_request(
        self,
        *,
        correlation_id: str,
        round_id: int | None,
        raw,
    ) -> None:
        self._writer.write({
            "record_type": "request",
            "correlation_id": correlation_id,
            "round_id": round_id,
            "payload": self._normalize(raw),
        })

    def record_response(
        self,
        *,
        correlation_id: str,
        round_id: int | None,
        raw_json: str,
    ) -> None:
        try:
            payload = json.loads(
                raw_json
            )
        except Exception:
            payload = raw_json

        self._writer.write({
            "record_type": "response",
            "correlation_id": correlation_id,
            "round_id": round_id,
            "payload": payload,
        })

    def record_error(
        self,
        *,
        correlation_id: str,
        error_code: str,
        message: str,
    ) -> None:
        self._writer.write({
            "record_type": "error",
            "correlation_id": correlation_id,
            "error_code": error_code,
            "message": message,
        })

    def close(self) -> None:
        self._writer.close()

    @staticmethod
    def _normalize(raw):
        if isinstance(raw, Mapping):
            return to_jsonable(raw)

        if isinstance(
            raw,
            (bytes, bytearray),
        ):
            raw = raw.decode(
                "utf-8",
                errors="replace",
            )

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return raw

        return to_jsonable(raw)
