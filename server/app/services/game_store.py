"""对局内存仓库：插入序即 LRU，超过上限淘汰最久未用的那一局。

为什么抽出来
------------
扑克与麻将的对局都是**进程内内存态**（不落库、重启即清），两边各自维护一份 dict
就得把「上限淘汰 + 取出即刷新」抄两遍 —— v0.66.0 麻将那份就因为漏了刷新写法踩过坑
（`move_to_end` 是 OrderedDict 的方法、普通 dict 没有，直接调用会让接口 500）。
一份实现、一处注释，两边共用。

用法::

    GAMES = GameStore(max_games=200)     # 模块级单例
    GAMES.remember(gid, rec)             # 开局
    rec = GAMES.recall(gid)              # 取用（不存在返回 None，404 文案由调用方决定）

上限只是防止长跑时无界增长；对局本身重启即清，不需要持久化。
"""


class GameStore(dict):
    """game_id → 对局记录；被 `recall()` 取过就刷新为「最近使用」。"""

    def __init__(self, max_games: int):
        super().__init__()
        self.max_games = max_games

    def remember(self, gid, rec):
        """记住一局；超过上限淘汰最久未使用的（dict 在 3.7+ 保序，队首即最久未用）。"""
        self[gid] = rec
        while len(self) > self.max_games:
            self.pop(next(iter(self)))
        return rec

    def recall(self, gid):
        """取出并标记「最近使用」；不存在返回 None。

        用「先 pop 再赋值」把条目挪到末尾（普通 dict 没有 `move_to_end`）。
        """
        rec = self.get(gid)
        if rec is not None:
            del self[gid]
            self[gid] = rec
        return rec
