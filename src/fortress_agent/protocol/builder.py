from __future__ import annotations

from collections import Counter
from types import MappingProxyType

from fortress_agent.game_rules.catalog import building_max_hp

from fortress_agent.domain.state import (
    BuildingState,
    CharacterState,
    EnemyState,
    GameState,
    InventoryItem,
    NeutralZoneState,
    ObservedCell,
    Position,
    ResourceNodeState,
    ServerErrorState,
    TaskState,
    WorldNewsState,
)
from .inbound import GameStateDTO
from fortress_agent.game_rules.constants import DAY_TURNS, NIGHT_TURNS, DAY_CYCLE_TURNS, ROBOT_ATTACK_RANGE
from fortress_agent.game_rules.catalog import ROBOT_RULES
from .server_inbound import ServerGameResponseDTO


_CHARACTER_TYPES = {"worker", "pioneer"}
_BUILDING_TYPES = {
    "station",
    "gatling",
    "railgun",
    "rocket",
    "wall",
}
_RESOURCE_TYPES = {"stone", "iron", "copper"}


class GameStateBuilder:
    def build(self, dto: GameStateDTO) -> GameState:
        return GameState(
            round_id=dto.round_id,
            day=dto.day,
            phase=dto.phase.strip().lower(),
            phase_round=dto.phase_round,
            turns_until_phase_change=dto.turns_until_phase_change,
            score_self=dto.score_self,
            score_opponent=dto.score_opponent,
            anomaly_count=dto.anomaly_count,
            characters=tuple(self._character(x) for x in dto.characters),
            enemies=tuple(self._enemy(x) for x in dto.enemies),
            buildings=tuple(self._building(x) for x in dto.buildings),
            resources=tuple(self._resource(x) for x in dto.resources),
            tasks=tuple(self._task(x) for x in dto.tasks),
            observed_cells=tuple(
                ObservedCell(x=x.x, y=x.y, terrain=x.terrain)
                for x in dto.observed_cells
            ),
            news=tuple(dto.news),
            rumors=tuple(dto.rumors),
            market_prices=MappingProxyType(dict(dto.market_prices)),
        )

    def build_server(self, dto: ServerGameResponseDTO) -> GameState:
        day, phase, phase_round, remaining = self._derive_phase(dto.roundNo)

        own_characters: list[CharacterState] = []
        opponent_characters: list[CharacterState] = []
        buildings: list[BuildingState] = []

        for role in dto.teamOur.roles:
            role_type = role.roleType.strip().lower()
            if self._is_character(role_type, role.backPackCapability):
                own_characters.append(
                    self._server_character(role)
                )
            else:
                buildings.append(
                    self._server_building(role, owner="self")
                )

        for role in dto.teamEnemy.roles:
            role_type = role.roleType.strip().lower()
            if self._is_character(role_type, role.backPackCapability):
                opponent_characters.append(
                    self._server_character(role)
                )
            else:
                buildings.append(
                    self._server_building(role, owner="opponent")
                )

        resources: list[ResourceNodeState] = []
        neutral_zones: list[NeutralZoneState] = []

        for zone in dto.mapInfo.zones:
            zone_type = zone.neutralType.strip()
            pos = Position(zone.pos.x, zone.pos.y)
            neutral_zones.append(
                NeutralZoneState(
                    zone_type=zone_type,
                    position=pos,
                )
            )

            if zone_type.lower() in _RESOURCE_TYPES:
                resources.append(
                    ResourceNodeState(
                        resource_id=(
                            f"zone:{zone_type.lower()}:"
                            f"{pos.x}:{pos.y}"
                        ),
                        resource_type=zone_type.lower(),
                        position=pos,
                        amount=None,
                        active=True,
                    )
                )

        tasks = tuple(
            TaskState(
                task_id=(
                    f"task:{task.taskType}:"
                    f"{task.taskPosition.x}:"
                    f"{task.taskPosition.y}"
                ),
                task_type=task.taskType,
                status="available" if task.isValid else "invalid",
                position=Position(
                    task.taskPosition.x,
                    task.taskPosition.y,
                ),
                reward=float(task.scoreReward),
                standard_turns=(task.timeoutRounds or None),
                accepted_round=None,
                payload=MappingProxyType({
                    "cooldown_rounds": task.coldDownRounds,
                    "gold_reward": task.goldReward,
                    "is_valid": task.isValid,
                    "timeout_rounds": task.timeoutRounds,
                }),
                timeout_rounds=task.timeoutRounds,
            )
            for task in dto.teamOur.playerTasks
        )

        enemies = tuple(
            self._server_robot(robot)
            for robot in dto.robot.roles
        )

        vendor_prices = MappingProxyType({
            item.name.lower(): float(item.price)
            for item in dto.vendorShopList
        })

        weapon_prices = MappingProxyType({
            item.name: float(item.price)
            for item in dto.weaponShopList
        })

        official_news = dto.worldNews.officialNews.strip()
        folk_legends = dto.worldNews.folkLegends.strip()

        return GameState(
            round_id=dto.roundNo,
            day=day,
            phase=phase,
            phase_round=phase_round,
            turns_until_phase_change=remaining,
            score_self=float(dto.teamOur.totalScore),
            score_opponent=float(dto.teamEnemy.totalScore),
            anomaly_count=0,
            characters=tuple(own_characters),
            enemies=enemies,
            buildings=tuple(buildings),
            resources=tuple(resources),
            tasks=tasks,
            observed_cells=(),
            news=(official_news,) if official_news else (),
            rumors=(folk_legends,) if folk_legends else (),
            market_prices=vendor_prices,
            team_type=dto.teamOur.type,
            team_id=dto.teamOur.teamId,
            team_name=dto.teamOur.teamName,
            gold_self=dto.teamOur.goldNum,
            opponent_characters=tuple(opponent_characters),
            neutral_zones=tuple(neutral_zones),
            weapon_shop=weapon_prices,
            world_news=WorldNewsState(
                official_news=official_news,
                folk_legends=folk_legends,
            ),
            raw_llm_response=dto.llmResp,
            phase_task=dto.phaseTask,
            last_command_result=dto.lastCmdResult,
            last_summon_treasure_result=dto.lastSummonTreasureResult,
            last_round_role_action_results=MappingProxyType(
                dict(dto.lastRoundRoleActionResults)
            ),
            round_error_count=len(dto.errors),
            server_errors=tuple(
                ServerErrorState(
                    error_code=error.errorCode,
                    description=error.description,
                )
                for error in dto.errors
            ),
            map_width=dto.mapInfo.width,
            map_height=dto.mapInfo.height,
            # mapInfo.zones is treated as the authoritative current neutral-zone
            # list returned by this protocol.
            map_snapshot_complete=True,
        )

    @staticmethod
    def _derive_phase(round_no: int) -> tuple[int, str, int, int]:
        day = ((round_no - 1) // DAY_CYCLE_TURNS) + 1
        round_in_day = ((round_no - 1) % DAY_CYCLE_TURNS) + 1

        if round_in_day <= DAY_TURNS:
            phase = "day"
            phase_round = round_in_day
            remaining = DAY_TURNS - phase_round
        else:
            phase = "night"
            phase_round = round_in_day - DAY_TURNS
            remaining = NIGHT_TURNS - phase_round

        return day, phase, phase_round, remaining

    @staticmethod
    def _is_character(role_type: str, backpack_capacity: int) -> bool:
        return (
            role_type in _CHARACTER_TYPES
            or (
                role_type not in _BUILDING_TYPES
                and backpack_capacity > 0
            )
        )

    def _server_character(self, role) -> CharacterState:
        counts = Counter(role.backpack)
        return CharacterState(
            actor_id=role.id,
            role=role.roleType.strip().lower(),
            hp=role.health,
            max_hp=(
                220
                if role.roleType.strip().lower() == "worker"
                else 200
                if role.roleType.strip().lower() == "pioneer"
                else None
            ),
            position=Position(role.pos.x, role.pos.y),
            backpack_capacity=role.backPackCapability,
            inventory=tuple(
                InventoryItem(
                    item_type=name.lower(),
                    amount=amount,
                )
                for name, amount in sorted(counts.items())
            ),
            attack_power=role.attackPower,
            attack_range=role.attackRange,
            level=role.level,
            cooldown=role.cooldown,
        )

    @staticmethod
    def _server_building(role, *, owner: str) -> BuildingState:
        return BuildingState(
            building_id=role.id,
            building_type=role.roleType.strip().lower(),
            position=Position(role.pos.x, role.pos.y),
            hp=role.health,
            max_hp=building_max_hp(role.roleType, role.level),
            owner=owner,
            cooldown_remaining=role.cooldown,
            attack_power=role.attackPower,
            attack_range=role.attackRange,
            level=role.level,
            footprint_width=(2 if role.roleType.strip().lower() == "station" else 1),
            footprint_height=(2 if role.roleType.strip().lower() == "station" else 1),
            footprint_anchor=("top_left" if role.roleType.strip().lower() == "station" else "cell"),
        )

    @staticmethod
    def _server_robot(robot) -> EnemyState:
        robot_type = robot.roleType.strip().lower()
        robot_rule = ROBOT_RULES.get(robot_type)
        attack = robot_rule.attack if robot_rule is not None else 0
        max_hp = robot_rule.max_hp if robot_rule is not None else robot.health
        score = robot_rule.score_value if robot_rule is not None else 0
        return EnemyState(
            enemy_id=robot.id,
            enemy_type=robot_type,
            hp=robot.health,
            max_hp=max_hp,
            attack=attack,
            attack_range=ROBOT_ATTACK_RANGE,
            score_value=score,
            position=Position(robot.pos.x, robot.pos.y),
            abnormal_state=robot.abnormalState,
            target_team=robot.targetTeam,
        )

    @staticmethod
    def _position(dto) -> Position:
        return Position(x=dto.x, y=dto.y)

    def _character(self, dto) -> CharacterState:
        inventory = tuple(
            InventoryItem(item_type=name, amount=amount)
            for name, amount in sorted(dto.inventory.items())
        )
        return CharacterState(
            actor_id=dto.actor_id,
            role=dto.role.strip().lower(),
            hp=dto.hp,
            max_hp=dto.max_hp,
            position=self._position(dto.position),
            backpack_capacity=dto.backpack_capacity,
            inventory=inventory,
        )

    def _enemy(self, dto) -> EnemyState:
        return EnemyState(
            enemy_id=dto.enemy_id,
            enemy_type=dto.enemy_type.strip().lower(),
            hp=dto.hp,
            max_hp=dto.max_hp,
            attack=dto.attack,
            attack_range=None,
            score_value=dto.score_value,
            position=self._position(dto.position),
        )

    def _building(self, dto) -> BuildingState:
        return BuildingState(
            building_id=dto.building_id,
            building_type=dto.building_type.strip().lower(),
            position=self._position(dto.position),
            hp=dto.hp,
            max_hp=dto.max_hp,
            owner=dto.owner,
            cooldown_remaining=dto.cooldown_remaining,
        )

    def _resource(self, dto) -> ResourceNodeState:
        return ResourceNodeState(
            resource_id=dto.resource_id,
            resource_type=dto.resource_type.strip().lower(),
            position=self._position(dto.position),
            amount=dto.amount,
            active=dto.active,
        )

    def _task(self, dto) -> TaskState:
        return TaskState(
            task_id=dto.task_id,
            task_type=dto.task_type.strip().lower(),
            status=dto.status.strip().lower(),
            position=self._position(dto.position) if dto.position else None,
            reward=dto.reward,
            standard_turns=dto.standard_turns,
            accepted_round=dto.accepted_round,
            payload=MappingProxyType(dict(dto.payload)),
        )
