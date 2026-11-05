"""牌 —— 川麻只有万/条/筒 3 门 × 1-9，每张 4 副，共 108 张。

和德扑的 `cards.py` 一样，牌是不可变对象，可以直接当 dict key / 放进 set。
川麻没有风牌（东南西北）和箭牌（中发白），所以不存在"字牌"这一整类，
手牌结构也简单得多：只有 27 个牌种。

索引约定：`Tile.idx = SUITS.index(suit) * 9 + rank - 1`，落在 0..26。
手牌一律转成 **27 长度的计数数组** 参与算法 —— 向听/进张要跑上万次，
用对象比较会慢一个量级（德扑 equity 热循环那次已经吃过这个亏）。
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

SUITS = ("m", "s", "p")                      # 万 / 条 / 筒
SUIT_NAMES = {"m": "万", "s": "条", "p": "筒"}
CN_NUMBERS = ("", "一", "二", "三", "四", "五", "六", "七", "八", "九")   # 下标 1..9
RANKS = tuple(range(1, 10))
N_KINDS = 27                                 # 3 门 × 9 点
TILES_PER_KIND = 4
WALL_SIZE = N_KINDS * TILES_PER_KIND         # 108


@dataclass(frozen=True, order=True)
class Tile:
    suit: str
    rank: int

    @property
    def code(self) -> str:
        """机器用的紧凑编码（`3m`）—— 接口、牌墙、进张等**数据传输**一律用这个。"""
        return f"{self.rank}{self.suit}"

    @property
    def name(self) -> str:
        """给人看的读数（`三万`）。

        用汉字数字而不是 `3万`：牌桌上说「碰三万」，没人说「碰 3 万」，
        而且前端按钮、出牌记录都直接显示这个串。
        """
        return f"{CN_NUMBERS[self.rank]}{SUIT_NAMES[self.suit]}"

    @property
    def idx(self) -> int:
        return SUITS.index(self.suit) * 9 + self.rank - 1

    def __repr__(self) -> str:
        return self.code


def tile_at(idx: int) -> Tile:
    """索引 → 牌。和 `Tile.idx` 互逆。"""
    suit, r = divmod(idx, 9)
    return Tile(SUITS[suit], r + 1)


def parse(code: str) -> Tile:
    """`"3m"` → Tile(万, 3)。兼容 `"m3"` 与 `"3万"` 写法。"""
    code = code.strip()
    if len(code) == 2 and code[0].isdigit():
        return Tile(code[1].lower(), int(code[0]))
    if len(code) == 2:
        return Tile(code[0].lower(), int(code[1]))
    for s, cn in SUIT_NAMES.items():          # "3万"
        if code.endswith(cn):
            return Tile(s, int(code[:-1]))
    raise ValueError(f"无法解析的牌: {code!r}")


def parse_many(text: str) -> List[Tile]:
    """`"123m 456s 789p"` / `"123m456s789p"` → 牌列表。空格与逗号都可作分隔。"""
    if "," in text:
        return [parse(x) for x in text.replace(" ", "").split(",") if x]
    out: List[Tile] = []
    buf = ""
    for ch in text:
        if ch.isdigit():
            buf += ch
        elif ch.strip():
            out.extend(Tile(ch.lower(), int(d)) for d in buf)
            buf = ""
    if buf:
        raise ValueError(f"结尾的门牌缺了门名: {text!r}")
    return out


def make_wall() -> List[Tile]:
    """108 张：3 门 × 9 点 × 4 张。"""
    return [Tile(s, r) for s in SUITS for r in RANKS for _ in range(TILES_PER_KIND)]


# ---------- 计数数组 ----------
def to_counts(tiles: Sequence[Tile]) -> List[int]:
    c = [0] * N_KINDS
    for t in tiles:
        c[t.idx] += 1
    return c


def from_counts(c: Sequence[int]) -> List[Tile]:
    return [tile_at(i) for i, n in enumerate(c) for _ in range(n)]


def counts_to_dict(tiles: Sequence[Tile]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for t in tiles:
        d[t.code] = d.get(t.code, 0) + 1
    return d


def suit_of(idx: int) -> str:
    return SUITS[idx // 9]


def rank_of(idx: int) -> int:
    return idx % 9 + 1


def is_valid_hand(counts: Sequence[int]) -> bool:
    """每张不超过 4 副（牌墙只有 4 张）。"""
    return all(0 <= n <= TILES_PER_KIND for n in counts)


def remaining(counts: Sequence[int], seen: Iterable[Tile] = ()) -> List[int]:
    """牌墙里还剩几张（用于算进张的剩余枚数）。
    河里的明牌由调用方传 `seen` 扣除。"""
    left = [TILES_PER_KIND - n for n in counts]
    for t in seen:
        left[t.idx] -= 1
    return left
