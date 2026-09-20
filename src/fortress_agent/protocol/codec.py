from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError

from fortress_agent.domain.state import GameState

from .builder import GameStateBuilder
from .inbound import GameStateDTO
from .outbound import GameActionResponse
from .result import CodecResult, ValidationIssue
from .server_inbound import ServerGameResponseDTO
from .server_outbound import ServerCommandResponse


class GameProtocolCodec:
    _WRAPPER_KEYS = ("data", "state", "game_state")

    def __init__(self, builder: GameStateBuilder | None = None):
        self._builder = builder or GameStateBuilder()

    def parse_state(
        self,
        raw: str | bytes | bytearray | Mapping[str, Any],
    ) -> CodecResult[GameState]:
        try:
            payload = self._to_mapping(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            return CodecResult.failure(
                error_code="invalid_json",
                message=str(exc),
            )

        payload = self._unwrap(payload)

        try:
            if "roundNo" in payload:
                dto = ServerGameResponseDTO.model_validate(payload)
                state = self._builder.build_server(dto)
            else:
                dto = GameStateDTO.model_validate(payload)
                state = self._builder.build(dto)
        except ValidationError as exc:
            return CodecResult.failure(
                error_code="state_validation_error",
                message="server state failed schema validation",
                issues=self._issues(exc),
            )
        except Exception as exc:
            return CodecResult.failure(
                error_code="state_build_error",
                message=str(exc),
            )

        return CodecResult.success(state)

    def serialize_response(self, response: GameActionResponse) -> CodecResult[str]:
        try:
            validated = GameActionResponse.model_validate(response)
            raw = validated.model_dump_json(
                exclude_none=True,
                by_alias=True,
            )
        except ValidationError as exc:
            return CodecResult.failure(
                error_code="response_validation_error",
                message="outbound response failed schema validation",
                issues=self._issues(exc),
            )
        except (TypeError, ValueError) as exc:
            return CodecResult.failure(
                error_code="response_serialization_error",
                message=str(exc),
            )

        return CodecResult.success(raw)


    def serialize_server_response(
        self,
        response: ServerCommandResponse,
    ) -> CodecResult[str]:
        try:
            validated = ServerCommandResponse.model_validate(
                response
            )
            raw = validated.model_dump_json(
                exclude_none=True,
            )
        except ValidationError as exc:
            return CodecResult.failure(
                error_code="server_response_validation_error",
                message=(
                    "real outbound response failed "
                    "schema validation"
                ),
                issues=self._issues(exc),
            )
        except (TypeError, ValueError) as exc:
            return CodecResult.failure(
                error_code="server_response_serialization_error",
                message=str(exc),
            )

        return CodecResult.success(raw)

    @staticmethod
    def _to_mapping(raw):
        if isinstance(raw, Mapping):
            return raw

        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("top-level JSON must be an object")
        return data

    def _unwrap(self, payload):
        for key in self._WRAPPER_KEYS:
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return payload

    @staticmethod
    def _issues(exc: ValidationError) -> tuple[ValidationIssue, ...]:
        return tuple(
            ValidationIssue(
                path=".".join(
                    str(part)
                    for part in error.get("loc", ())
                ),
                message=error.get("msg", "validation error"),
                error_type=error.get("type", "unknown"),
            )
            for error in exc.errors(include_url=False)
        )
