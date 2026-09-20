from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from pydantic import TypeAdapter, ValidationError

from fortress_agent.domain.state import GameState

from .result import ValidationIssue
from .server_outbound import (
    RoleCommand,
    ServerCommandResponse,
)


_ROLE_COMMAND_ADAPTER = TypeAdapter(RoleCommand)


@dataclass(frozen=True, slots=True)
class RoleCommandFailure:
    role_id: str
    error_code: str
    message: str
    issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class SafeCommandBuildResult:
    response: ServerCommandResponse
    failures: tuple[RoleCommandFailure, ...]
    fallback_roles: tuple[str, ...]
    omitted_roles: tuple[str, ...]

    @property
    def degraded(self) -> bool:
        return bool(
            self.failures
            or self.fallback_roles
            or self.omitted_roles
        )


class RoleCommandFallbackResolver(Protocol):
    def resolve(
        self,
        *,
        role_id: str,
        invalid_command: object,
        state: GameState | None,
        failure: RoleCommandFailure,
    ) -> RoleCommand | Mapping[str, object] | None:
        ...


class OmitInvalidRoleCommandFallback:
    """Safest protocol-level fallback.

    The protocol shows roleCommandMap as a mapping, so a role without a
    verified command can be omitted. We never invent WAIT or a movement target.
    """

    def resolve(
        self,
        *,
        role_id: str,
        invalid_command: object,
        state: GameState | None,
        failure: RoleCommandFailure,
    ):
        return None


class StaticRoleCommandFallback:
    """Inject known-good emergency commands prepared by the safety layer."""

    def __init__(
        self,
        commands: Mapping[
            str,
            RoleCommand | Mapping[str, object],
        ],
    ) -> None:
        self._commands = dict(commands)

    def resolve(
        self,
        *,
        role_id: str,
        invalid_command: object,
        state: GameState | None,
        failure: RoleCommandFailure,
    ):
        return self._commands.get(role_id)


class SafeServerResponseBuilder:
    def __init__(
        self,
        fallback: RoleCommandFallbackResolver | None = None,
    ) -> None:
        self._fallback = (
            fallback
            or OmitInvalidRoleCommandFallback()
        )

    def build(
        self,
        role_commands: Mapping[
            str | int,
            RoleCommand | Mapping[str, object],
        ],
        *,
        prompt: str | None = "",
        execute_cmd: str | None = "",
        state: GameState | None = None,
    ) -> SafeCommandBuildResult:
        validated: dict[str, RoleCommand] = {}
        failures: list[RoleCommandFailure] = []
        fallback_roles: list[str] = []
        omitted_roles: list[str] = []

        for raw_role_id, raw_command in role_commands.items():
            role_id = str(raw_role_id).strip()

            if not role_id:
                failures.append(
                    RoleCommandFailure(
                        role_id="",
                        error_code="empty_role_id",
                        message="role id must be non-empty",
                    )
                )
                continue

            command, failure = self._validate(
                role_id,
                raw_command,
            )

            if command is not None:
                validated[role_id] = command
                continue

            assert failure is not None
            failures.append(failure)

            fallback = self._fallback.resolve(
                role_id=role_id,
                invalid_command=raw_command,
                state=state,
                failure=failure,
            )

            if fallback is None:
                omitted_roles.append(role_id)
                continue

            fallback_command, fallback_failure = (
                self._validate(
                    role_id,
                    fallback,
                    error_code="invalid_fallback_command",
                )
            )

            if fallback_command is None:
                assert fallback_failure is not None
                failures.append(fallback_failure)
                omitted_roles.append(role_id)
                continue

            validated[role_id] = fallback_command
            fallback_roles.append(role_id)

        response = ServerCommandResponse(
            roleCommandMap=validated,
            prompt=prompt,
            executeCmd=execute_cmd,
        )

        return SafeCommandBuildResult(
            response=response,
            failures=tuple(failures),
            fallback_roles=tuple(fallback_roles),
            omitted_roles=tuple(omitted_roles),
        )

    @staticmethod
    def _validate(
        role_id: str,
        raw_command,
        *,
        error_code: str = "invalid_role_command",
    ):
        try:
            return (
                _ROLE_COMMAND_ADAPTER.validate_python(
                    raw_command
                ),
                None,
            )
        except ValidationError as exc:
            issues = tuple(
                ValidationIssue(
                    path=".".join(
                        str(part)
                        for part in error.get("loc", ())
                    ),
                    message=error.get(
                        "msg",
                        "validation error",
                    ),
                    error_type=error.get(
                        "type",
                        "unknown",
                    ),
                )
                for error in exc.errors(
                    include_url=False
                )
            )

            return (
                None,
                RoleCommandFailure(
                    role_id=role_id,
                    error_code=error_code,
                    message=(
                        "role command failed "
                        "wire schema validation"
                    ),
                    issues=issues,
                ),
            )
