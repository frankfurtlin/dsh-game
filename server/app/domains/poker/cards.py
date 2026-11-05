"""扑克牌基础：Card / 牌堆 / 洗牌。纯标准库。"""
import random
from typing import List

RANKS = "23456789TJQKA"          # 2..14 (A=14)
SUITS = "shdc"                   # spade / heart / diamond / club


class Card:
    __slots__ = ("rank", "suit", "code", "rv")

    def __init__(self, code: str):
        # code 形如 'As' 'Td' '9c'（点数+花色）
        self.rank = code[0]
        self.suit = code[1]
        self.code = code
        self.rv = RANKS.index(self.rank) + 2   # 2->2 ... A->14

    def __repr__(self) -> str:
        return self.code

    def __eq__(self, other) -> bool:
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)


def make_deck() -> List[Card]:
    return [Card(r + s) for r in RANKS for s in SUITS]


def shuffle(deck: List[Card], rng: random.Random = None) -> None:
    (rng or random).shuffle(deck)


def deal(n_players: int, cards_each: int, community: int, rng: random.Random = None):
    """发牌工具：返回 (hands, community, remaining)。
    n_players*cards_each + community 张牌从牌堆顺序取出。"""
    rng = rng or random
    deck = make_deck()
    rng.shuffle(deck)
    hands = [[deck.pop() for _ in range(cards_each)] for _ in range(n_players)]
    comm = [deck.pop() for _ in range(community)]
    return hands, comm, deck


if __name__ == "__main__":
    d = make_deck()
    print("deck size:", len(d))
    print("sample:", d[:5])
