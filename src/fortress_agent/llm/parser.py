from __future__ import annotations

import json
from typing import Mapping

from pydantic import ValidationError

from fortress_agent.protocol.result import CodecResult, ValidationIssue

from .schema import StrategicAdvisory


class StrategicLLMResponseParser:
    """Strict JSON -> StrategicAdvisory parser.

    Markdown/prose is never accepted as strategy input. A single outer
    ```json ... ``` transport fence is tolerated, but its content must still
    be valid JSON matching the Pydantic schema exactly.
    """

    def parse(
        self,
        raw: str | Mapping[str, object],
    ) -> CodecResult[StrategicAdvisory]:
        try:
            if isinstance(raw, Mapping):
                payload = dict(raw)
            else:
                text = self._strip_json_fence(raw.strip())
                if not text:
                    return CodecResult.failure(
                        error_code="empty_llm_response",
                        message="LLM response is empty",
                    )
                payload = json.loads(text)

            if not isinstance(payload, dict):
                raise TypeError(
                    "LLM strategic response must be a JSON object"
                )
        except (json.JSONDecodeError, TypeError) as exc:
            return CodecResult.failure(
                error_code="llm_invalid_json",
                message=str(exc),
            )

        try:
            advisory = StrategicAdvisory.model_validate(payload)
        except ValidationError as exc:
            return CodecResult.failure(
                error_code="llm_schema_validation_error",
                message="LLM response failed strategic schema validation",
                issues=tuple(
                    ValidationIssue(
                        path=".".join(
                            str(part)
                            for part in error.get("loc", ())
                        ),
                        message=error.get("msg", "validation error"),
                        error_type=error.get("type", "unknown"),
                    )
                    for error in exc.errors(include_url=False)
                ),
            )

        return CodecResult.success(advisory)

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        if not text.startswith("```"):
            return text

        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            return text

        first = lines[0].strip().lower()
        if first not in {"```", "```json"}:
            return text

        return "\n".join(lines[1:-1]).strip()
