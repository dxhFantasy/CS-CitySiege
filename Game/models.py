"""数据模型：阵营、部队、城市与回合指令。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Pos = tuple[int, int]


class Faction(Enum):
    """阵营。NEUTRAL 只用于中立城市与中立领土。"""

    RED = "red"
    BLUE = "blue"
    NEUTRAL = "neutral"

    @property
    def DisplayName(self) -> str:
        """中文显示名。"""
        names: dict[str, str] = {"red": "红方", "blue": "蓝方", "neutral": "中立"}
        return names[self.value]

    @property
    def Enemy(self) -> Faction:
        """敌对阵营；中立返回自身。"""
        if self is Faction.RED:
            return Faction.BLUE
        if self is Faction.BLUE:
            return Faction.RED
        return Faction.NEUTRAL


@dataclass
class Stack:
    """一格上的部队。moved 表示本回合是否已经下达过指令。"""

    faction: Faction
    count: int
    moved: bool = False


@dataclass
class City:
    """城市。"""

    x: int
    y: int
    faction: Faction


@dataclass
class Order:
    """回合内下达、回合结束时统一结算的移动/攻击指令。"""

    faction: Faction
    fromX: int
    fromY: int
    toX: int
    toY: int
