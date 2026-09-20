from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServerInboundModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        frozen=True,
    )


class ServerPositionDTO(ServerInboundModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class MapZoneDTO(ServerInboundModel):
    neutralType: str
    pos: ServerPositionDTO


class MapInfoDTO(ServerInboundModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    zones: list[MapZoneDTO] = Field(default_factory=list)


class PlayerTaskDTO(ServerInboundModel):
    taskType: str
    taskPosition: ServerPositionDTO
    coldDownRounds: int = Field(default=0, ge=0)
    scoreReward: float = 0.0
    goldReward: int = 0
    isValid: bool = True
    timeoutRounds: int = Field(default=0, ge=0)


class RoleDTO(ServerInboundModel):
    id: str | int
    pos: ServerPositionDTO
    roleType: str
    health: int = Field(ge=0)
    attackPower: int = Field(default=0, ge=0)
    attackRange: int = Field(default=0, ge=0)
    level: int | None = Field(default=None, ge=0)
    backPackCapability: int = Field(default=0, ge=0)
    backpack: list[str] = Field(default_factory=list)
    cooldown: int = Field(default=0, ge=0)

    @property
    def inventory_counts(self) -> dict[str, int]:
        return dict(Counter(self.backpack))


class TeamOurDTO(ServerInboundModel):
    type: str | None = None
    teamId: str | None = None
    teamName: str | None = None
    goldNum: int = Field(default=0, ge=0)
    totalScore: float = 0.0
    playerTasks: list[PlayerTaskDTO] = Field(default_factory=list)
    roles: list[RoleDTO] = Field(default_factory=list)


class TeamEnemyDTO(ServerInboundModel):
    type: str | None = None
    teamId: str | None = None
    teamName: str | None = None
    totalScore: float = 0.0
    roles: list[RoleDTO] = Field(default_factory=list)


class RobotRoleDTO(ServerInboundModel):
    id: str | int
    pos: ServerPositionDTO
    roleType: str
    health: int = Field(ge=0)
    abnormalState: str = ""
    targetTeam: str | None = None


class RobotDTO(ServerInboundModel):
    roles: list[RobotRoleDTO] = Field(default_factory=list)


class WorldNewsDTO(ServerInboundModel):
    officialNews: str = ""
    folkLegends: str = ""


class ShopItemDTO(ServerInboundModel):
    name: str
    price: float = Field(ge=0)


class ServerErrorDTO(ServerInboundModel):
    errorCode: int
    description: str = ""


class ServerGameResponseDTO(ServerInboundModel):
    roundNo: int = Field(ge=1)
    mapInfo: MapInfoDTO

    teamOur: TeamOurDTO
    teamEnemy: TeamEnemyDTO = Field(default_factory=TeamEnemyDTO)
    robot: RobotDTO = Field(default_factory=RobotDTO)

    phaseTask: str = ""
    lastRoundRoleActionResults: dict[str, bool] = Field(default_factory=dict)
    lastSummonTreasureResult: int | None = None
    llmResp: str = ""

    worldNews: WorldNewsDTO = Field(default_factory=WorldNewsDTO)
    lastCmdResult: str = ""

    vendorShopList: list[ShopItemDTO] = Field(default_factory=list)
    weaponShopList: list[ShopItemDTO] = Field(default_factory=list)

    errors: list[ServerErrorDTO] = Field(default_factory=list)
