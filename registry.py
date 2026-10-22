from dataclasses import dataclass
from typing import Callable

COMMANDS: dict[str, "Cmd"] = {}


@dataclass
class Cmd:
    fn: Callable
    chat_only: bool = False
    mod: bool = False
    gate: bool = True


def cmd(*names, chat_only=False, mod=False, gate=True):
    def deco(fn):
        for n in names:
            COMMANDS[n] = Cmd(fn, chat_only or mod, mod, gate and not mod)
        return fn
    return deco
