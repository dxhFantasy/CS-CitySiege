"""规则引擎：棋盘状态、指令结算、战斗与胜负判定。"""

from __future__ import annotations

import random
from typing import Any, cast

from .constants import CITY_COST, GRID_SIZE, MAX_STACK, START_ZONE_RADIUS, CITY_MAX, CITY_DIS_MIN
from .models import City, Faction, Order, Pos, Stack


class GameState:
    """一局游戏的全部状态；联机时主机端持有权威副本。"""

    def __init__(self) -> None:
        """建立默认对局：两座主城、一座中立城，大部分地块中立。"""
        self.units: list[list[Stack | None]] = [
            [None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)
        ]
        self.territory: list[list[Faction]] = [
            [Faction.NEUTRAL for _ in range(GRID_SIZE)]
            for _ in range(GRID_SIZE)
        ]
        self.cities: list[City] = []
        self.orders: list[Order] = []
        self.turn: Faction = Faction.RED
        self.turnNumber: int = 1
        self.winner: Faction | None = None

        self.SetupInitialCities()
        self.SetupInitialTerritory()
        self.SetupInitialUnits()
        self.BeginTurn(Faction.RED)

    # ---- 初始化 ---------------------------------------------------------

    def SetupInitialCities(self) -> None:
        """三座城市的初始位置与归属。想换地图改这里。"""
        self.cities = [
            City(3, 8, Faction.RED),
            City(7, 8, Faction.NEUTRAL),
            City(12, 8, Faction.BLUE),
        ]

    def SetupInitialTerritory(self) -> None:
        """初始只有主城周围一小片领土，其余全部是中立地块。"""
        for faction in (Faction.RED, Faction.BLUE):
            home = next(
                (city for city in self.cities if city.faction is faction), None
            )
            if home is None:
                continue
            for y in range(home.y - START_ZONE_RADIUS, home.y + START_ZONE_RADIUS + 1):
                for x in range(
                    home.x - START_ZONE_RADIUS, home.x + START_ZONE_RADIUS + 1
                ):
                    if self.InBounds(x, y):
                        self.territory[y][x] = faction

    def SetupInitialUnits(self) -> None:
        """双方初始各有 3 叠、每叠 2 个士兵。想改初始兵力改这里。"""
        starting: list[tuple[int, int, Faction, int]] = [
            (4, 8, Faction.RED, 2),
            (3, 7, Faction.RED, 2),
            (3, 9, Faction.RED, 2),
            (11, 8, Faction.BLUE, 2),
            (12, 7, Faction.BLUE, 3),
            (12, 9, Faction.BLUE, 2),
        ]
        for x, y, faction, count in starting:
            self.units[y][x] = Stack(faction, count)

    # ---- 基础工具 -------------------------------------------------------

    def InBounds(self, x: int, y: int) -> bool:
        """坐标是否在棋盘内。"""
        return 0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE

    def Neighbors4(self, x: int, y: int) -> list[Pos]:
        """上下左右四个合法相邻格。"""
        result: list[Pos] = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.InBounds(nx, ny):
                result.append((nx, ny))
        return result

    def CityAt(self, x: int, y: int) -> City | None:
        """指定格上的城市。"""
        for city in self.cities:
            if city.x == x and city.y == y:
                return city
        return None

    def CountSoldiers(self, faction: Faction) -> int:
        """某阵营棋面上的士兵总数。"""
        total = 0
        for row in self.units:
            for stack in row:
                if stack is not None and stack.faction is faction:
                    total += stack.count
        return total

    # ---- 回合流程 -------------------------------------------------------

    def CitySpacingOk(self, x: int, y: int) -> bool:
        """新城市与所有已有城市的横纵轴间距之和必须不小于 2。"""
        for city in self.cities:
            deltaX = city.x - x
            deltaY = city.y - y
            if deltaX + deltaY < CITY_DIS_MIN:
                return False
        return True


    def BeginTurn(self, faction: Faction) -> None:
        """开始新回合：清空指令、重置行动标记、城市扩张与出兵。"""
        self.turn = faction
        self.orders = []
        for row in self.units:
            for stack in row:
                if stack is not None and stack.faction is faction:
                    stack.moved = False
        self.ClaimTerritory(faction)
        self.SpawnForFaction(faction)

    def EndTurn(self) -> None:
        """结束回合：先按顺序结算全部指令，再切换到下一方。"""
        if self.winner is not None:
            return
        self.ResolveOrders()
        self.CheckWinner()
        if self.winner is not None:
            return

        nextFaction = self.turn.Enemy
        if nextFaction not in (Faction.RED, Faction.BLUE):
            return
        if nextFaction is Faction.RED:
            self.turnNumber += 1
        self.BeginTurn(nextFaction)
        self.CheckWinner()

    # ---- 领土与出兵 -----------------------------------------------------

    def ClaimTerritory(self, faction: Faction) -> None:
        """城市把自身与十字相邻格纳入领土，不抢敌方城市/部队所在格。"""
        for city in self.cities:
            if city.faction is not faction:
                continue
            for cellX, cellY in [(city.x, city.y), *self.Neighbors4(city.x, city.y)]:
                stack = self.units[cellY][cellX]
                if stack is not None and stack.faction is faction.Enemy:
                    continue
                otherCity = self.CityAt(cellX, cellY)
                if otherCity is not None and otherCity.faction is not faction:
                    continue
                self.territory[cellY][cellX] = faction

    def SpawnForFaction(self, faction: Faction) -> None:
        """每个己方城市尝试在随机相邻格生成 1 个士兵。想改出兵规则看这里。"""
        directions: list[Pos] = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        for city in self.cities:
            if city.faction is not faction:
                continue
            options: list[Pos] = []
            for dx, dy in directions:
                targetX, targetY = city.x + dx, city.y + dy
                if not self.InBounds(targetX, targetY):
                    continue
                otherCity = self.CityAt(targetX, targetY)
                if otherCity is not None and otherCity.faction is not faction:
                    continue
                stack = self.units[targetY][targetX]
                if stack is None:
                    options.append((targetX, targetY))
                elif stack.faction is faction and stack.count < MAX_STACK:
                    options.append((targetX, targetY))
            if not options:
                continue
            spawnX, spawnY = random.choice(options)
            stack = self.units[spawnY][spawnX]
            if stack is None:
                self.units[spawnY][spawnX] = Stack(faction, 1)
            else:
                stack.count += 1
            self.territory[spawnY][spawnX] = faction

    # ---- 指令 -----------------------------------------------------------

    def ApplyOrder(self, faction: Faction, fromPos: Pos, toPos: Pos) -> bool:
        """下达移动/攻击指令；回合结束时才真正结算。"""
        if self.winner is not None or self.turn is not faction:
            return False
        fromX, fromY = fromPos
        toX, toY = toPos
        if not (self.InBounds(fromX, fromY) and self.InBounds(toX, toY)):
            return False
        if abs(fromX - toX) + abs(fromY - toY) != 1:
            return False

        source = self.units[fromY][fromX]
        if source is None or source.faction is not faction or source.moved:
            return False

        target = self.units[toY][toX]
        if (
            target is not None
            and target.faction is faction
            and target.count >= MAX_STACK
        ):
            return False

        self.orders.append(Order(faction, fromX, fromY, toX, toY))
        source.moved = True
        return True

    def CancelOrder(self, faction: Faction, pos: Pos) -> bool:
        """撤回某格部队已下达的指令。"""
        if self.winner is not None or self.turn is not faction:
            return False
        x, y = pos
        for index, order in enumerate(self.orders):
            if order.faction is faction and order.fromX == x and order.fromY == y:
                del self.orders[index]
                stack = self.units[y][x]
                if stack is not None and stack.faction is faction:
                    stack.moved = False
                return True
        return False

    def ApplyConvert(self, faction: Faction, pos: Pos) -> bool:
        """把一格 4 个士兵变成一个城市（立即生效，不消耗指令）。"""
        if self.winner is not None or self.turn is not faction:
            return False
        x, y = pos
        if not self.InBounds(x, y):
            return False
        if len(self.cities) >= CITY_MAX:
            return False
        stack = self.units[y][x]
        if stack is None or stack.faction is not faction:
            return False
        if stack.moved:
            return False
        if stack.count < CITY_COST:
            return False
        if self.CityAt(x, y) is not None:
            return False
        if not self.CitySpacingOk(x, y):
            return False


        stack.count -= CITY_COST
        if stack.count == 0:
            self.units[y][x] = None
        self.cities.append(City(x, y, faction))
        self.territory[y][x] = faction
        self.CheckWinner()
        return True

    # ---- 指令结算 -------------------------------------------------------

    def ResolveOrders(self) -> None:
        """结算所有指令。

        先结算“自身所在格是别的指令目标”的指令：这样目标格上的部队
        本回合离开后，后面的部队才能正常进入/整合。
        出现循环依赖（例如两支部队互换位置）时按原下单顺序处理。
        """
        orders = self.orders
        self.orders = []

        originIndex: dict[Pos, int] = {}
        for index, order in enumerate(orders):
            originIndex[(order.fromX, order.fromY)] = index

        resolved: list[bool] = [False] * len(orders)
        resolutionOrder: list[Order] = []

        def Visit(index: int, visiting: set[int]) -> None:
            """深度优先，把被依赖的出发格指令排到前面。"""
            if resolved[index] or index in visiting:
                return
            visiting.add(index)
            order = orders[index]
            blocker = originIndex.get((order.toX, order.toY))
            if blocker is not None and blocker != index:
                Visit(blocker, visiting)
            resolved[index] = True
            resolutionOrder.append(order)

        for index in range(len(orders)):
            Visit(index, set())

        for order in resolutionOrder:
            self.ResolveOrder(order)


    def ResolveOrder(self, order: Order) -> None:
        """结算一条指令：移动、整合或战斗。"""
        source = self.units[order.fromY][order.fromX]
        if source is None or source.faction is not order.faction:
            return

        target = self.units[order.toY][order.toX]

        if target is None:
            self.units[order.toY][order.toX] = Stack(
                order.faction, source.count, True
            )
            self.units[order.fromY][order.fromX] = None
            self.territory[order.toY][order.toX] = order.faction
            self.TryCaptureCity(order.toX, order.toY, order.faction)
            return

        if target.faction is order.faction:
            space = MAX_STACK - target.count
            if space <= 0:
                return
            moveCount = min(source.count, space)
            target.count += moveCount
            target.moved = True
            source.count -= moveCount
            if source.count <= 0:
                self.units[order.fromY][order.fromX] = None
            return

        attackerLeft, defenderLeft = self.ResolveBattle(source.count, target.count)
        if defenderLeft <= 0 and attackerLeft > 0:
            self.units[order.toY][order.toX] = Stack(
                order.faction, attackerLeft, True
            )
            self.units[order.fromY][order.fromX] = None
            self.territory[order.toY][order.toX] = order.faction
            self.TryCaptureCity(order.toX, order.toY, order.faction)
        elif defenderLeft <= 0 and attackerLeft <= 0:
            self.units[order.toY][order.toX] = None
            self.units[order.fromY][order.fromX] = None
        elif attackerLeft <= 0:
            target.count = defenderLeft
            self.units[order.fromY][order.fromX] = None
        else:
            target.count = defenderLeft
            source.count = attackerLeft

    @staticmethod
    def ResolveBattle(attackerCount: int, defenderCount: int) -> tuple[int, int]:
        """战斗公式：士兵数=攻防；对方≥3 时自己造成的伤害 -1。

        返回 (进攻方剩余, 防守方剩余)，双方同时结算。
        """
        attackerDamage = max(0, attackerCount - (1 if defenderCount >= 3 else 0))
        defenderDamage = max(0, defenderCount - (1 if attackerCount >= 3 else 0))
        return (
            max(0, attackerCount - defenderDamage),
            max(0, defenderCount - attackerDamage),
        )

    def TryCaptureCity(self, x: int, y: int, faction: Faction) -> None:
        """无守军的敌方城市被进入时易主。"""
        city = self.CityAt(x, y)
        if city is not None and city.faction is not faction:
            city.faction = faction
            self.territory[y][x] = faction

    # ---- 胜负 -----------------------------------------------------------

    def CheckWinner(self) -> Faction | None:
        """控制全部城市且对方士兵为 0 即获胜。"""
        if self.winner is not None:
            return self.winner
        for faction in (Faction.RED, Faction.BLUE):
            ownsAllCities = bool(self.cities) and all(
                city.faction is faction for city in self.cities
            )
            if ownsAllCities and self.CountSoldiers(faction.Enemy) == 0:
                self.winner = faction
                return faction
        return None

    # ---- 序列化 ---------------------------------------------------------

    def ToDict(self) -> dict[str, Any]:
        """序列化成可 JSON 传输的字典（主机发给客户端）。"""
        return {
            "units": [
                [
                    None
                    if stack is None
                    else [stack.faction.value, stack.count, stack.moved]
                    for stack in row
                ]
                for row in self.units
            ],
            "territory": [[cell.value for cell in row] for row in self.territory],
            "cities": [
                {"x": city.x, "y": city.y, "f": city.faction.value}
                for city in self.cities
            ],
            "orders": [
                {
                    "f": order.faction.value,
                    "fx": order.fromX,
                    "fy": order.fromY,
                    "tx": order.toX,
                    "ty": order.toY,
                }
                for order in self.orders
            ],
            "turn": self.turn.value,
            "turnNumber": self.turnNumber,
            "winner": None if self.winner is None else self.winner.value,
        }

    @classmethod
    def FromDict(cls, data: dict[str, Any]) -> GameState:
        """从主机状态字典重建（客户端用）。"""
        state = cls.__new__(cls)

        rawUnits = cast(list[list[list[Any] | None]], data["units"])
        rows: list[list[Stack | None]] = []
        for y in range(GRID_SIZE):
            row: list[Stack | None] = []
            for x in range(GRID_SIZE):
                entry = rawUnits[y][x]
                if entry is None:
                    row.append(None)
                else:
                    row.append(
                        Stack(
                            Faction(cast(str, entry[0])),
                            cast(int, entry[1]),
                            cast(bool, entry[2]),
                        )
                    )
            rows.append(row)
        state.units = rows

        rawTerritory = cast(list[list[str]], data["territory"])
        state.territory = [
            [Faction(value) for value in row] for row in rawTerritory
        ]

        rawCities = cast(list[dict[str, Any]], data["cities"])
        state.cities = [
            City(
                cast(int, item["x"]),
                cast(int, item["y"]),
                Faction(cast(str, item["f"])),
            )
            for item in rawCities
        ]

        rawOrders = cast(list[dict[str, Any]], data["orders"])
        state.orders = [
            Order(
                Faction(cast(str, item["f"])),
                cast(int, item["fx"]),
                cast(int, item["fy"]),
                cast(int, item["tx"]),
                cast(int, item["ty"]),
            )
            for item in rawOrders
        ]

        state.turn = Faction(cast(str, data["turn"]))
        state.turnNumber = cast(int, data["turnNumber"])
        rawWinner = data.get("winner")
        state.winner = None if rawWinner is None else Faction(cast(str, rawWinner))
        return state
