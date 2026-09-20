from __future__ import annotations

from dataclasses import dataclass
import hashlib

from fortress_agent.llm.schema import StrategicAdvisory


@dataclass(frozen=True, slots=True)
class LoreEntry:
    lore_id: str
    first_seen_round: int
    last_seen_round: int
    text: str


class StrategicMemory:
    def __init__(self) -> None:
        self._lore: dict[str, LoreEntry] = {}
        self._advisories: list[StrategicAdvisory] = []

    def observe_lore(
        self,
        *,
        round_id: int,
        text: str,
    ) -> bool:
        normalized = " ".join(text.split())
        if not normalized:
            return False

        lore_id = hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()[:16]

        existing = self._lore.get(lore_id)

        if existing is None:
            self._lore[lore_id] = LoreEntry(
                lore_id=lore_id,
                first_seen_round=round_id,
                last_seen_round=round_id,
                text=normalized,
            )
            return True

        self._lore[lore_id] = LoreEntry(
            lore_id=existing.lore_id,
            first_seen_round=existing.first_seen_round,
            last_seen_round=round_id,
            text=existing.text,
        )
        return False

    def add_advisory(
        self,
        advisory: StrategicAdvisory,
    ) -> None:
        self._advisories.append(advisory)

    def view(self) -> "StrategicMemoryView":
        return StrategicMemoryView(self)


class StrategicMemoryView:
    def __init__(self, memory: StrategicMemory) -> None:
        self._memory = memory

    def lore(self) -> tuple[LoreEntry, ...]:
        return tuple(
            sorted(
                self._memory._lore.values(),
                key=lambda x: (
                    x.first_seen_round,
                    x.lore_id,
                ),
            )
        )

    def active_advisory(
        self,
        round_id: int,
    ) -> StrategicAdvisory | None:
        valid = [
            advisory
            for advisory in self._memory._advisories
            if (
                advisory.source_round <= round_id
                and round_id
                <= advisory.source_round
                + advisory.expires_after_rounds
            )
        ]

        if not valid:
            return None

        # Newer, stronger advice wins deterministically.
        valid.sort(
            key=lambda advisory: (
                advisory.source_round,
                advisory.effective_strength,
            ),
            reverse=True,
        )
        return valid[0]


    def latest_advisory_source_round(
        self,
    ) -> int | None:
        if not self._memory._advisories:
            return None
        return max(
            advisory.source_round
            for advisory
            in self._memory._advisories
        )

    def pending_lore(
        self,
    ) -> tuple[LoreEntry, ...]:
        latest_source = (
            self.latest_advisory_source_round()
        )

        return tuple(
            entry
            for entry in self.lore()
            if (
                latest_source is None
                or entry.first_seen_round
                > latest_source
            )
        )
