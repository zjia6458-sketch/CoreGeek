from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    message: str
    error_type: str


@dataclass(frozen=True, slots=True)
class CodecResult(Generic[T]):
    ok: bool
    value: T | None = None
    error_code: str | None = None
    message: str | None = None
    issues: tuple[ValidationIssue, ...] = ()

    @classmethod
    def success(cls, value: T) -> "CodecResult[T]":
        return cls(ok=True, value=value)

    @classmethod
    def failure(
        cls,
        *,
        error_code: str,
        message: str,
        issues: tuple[ValidationIssue, ...] = (),
    ) -> "CodecResult[T]":
        return cls(
            ok=False,
            error_code=error_code,
            message=message,
            issues=issues,
        )
