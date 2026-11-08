from typing import IO, Any, Iterator

from pydantic import BaseModel

from beaver import BeaverDB, Secret
from beaver.interfaces import IBeaverDict


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


def can_sign_in(accounts: IBeaverDict[Agent], login: str, password: str) -> bool:
    agent = accounts.fetch(login)
    return agent is not None and agent.password == password


class MemoryDict[T]:
    """Every method of IBeaverDict, kept in memory, for tests."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def get(self, key: str) -> T:
        return self._items[key]

    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None:
        self._items[key] = value

    def delete(self, key: str) -> None:
        del self._items[key]

    def fetch(self, key: str, default: Any = None) -> T | Any:
        return self._items.get(key, default)

    def pop(self, key: str, default: Any = None) -> T | Any:
        return self._items.pop(key, default)

    def keys(self) -> Iterator[str]:
        return iter(list(self._items))

    def values(self) -> Iterator[T]:
        return iter(list(self._items.values()))

    def items(self) -> Iterator[tuple[str, T]]:
        return iter(list(self._items.items()))

    def clear(self) -> None:
        self._items.clear()

    def count(self) -> int:
        return len(self._items)

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        return {"items": list(self._items)}

    def load(
        self, fp: IO[str], format: str = "json", strategy: str = "overwrite"
    ) -> None:
        raise NotImplementedError

    __getitem__ = get
    __setitem__ = set
    __delitem__ = delete
    __len__ = count

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[str]:
        return self.keys()


def test_sign_in() -> None:
    accounts: MemoryDict[Agent] = MemoryDict()
    accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
    assert can_sign_in(accounts, "ana", "pw")
    assert not can_sign_in(accounts, "ana", "guess")
    assert not can_sign_in(accounts, "luis", "pw")


def main() -> None:
    test_sign_in()
    print("test_sign_in passed")
    with BeaverDB("helpdesk.db") as db:
        accounts = db.dict("accounts", model=Agent)
        accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
        print("on the real collection:", can_sign_in(accounts, "ana", "pw"))


if __name__ == "__main__":
    main()
