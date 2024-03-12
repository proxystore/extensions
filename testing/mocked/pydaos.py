"""Mock implementation of PyDAOS.

A lot of this code is either inneficient, not very pythonic, or just really
strange, but this is because it is verbatim from the reference implementation
where possible. There are some strange choices in it...

Reference implementation:
https://github.com/daos-stack/daos/blob/release/2.4/src/client/pydaos/pydaos_core.py
"""

from __future__ import annotations

from typing import Any
from typing import cast
from typing import Dict
from typing import Generator


class DObjNotFound(Exception):  # noqa: N818
    """Raised by get if name associated with DAOS object not found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(self)

    def __str__(self) -> str:
        return 'Failed to open "{self.name}"'


class DCont:
    """Class representing a DAOS Python container."""

    def __init__(
        self,
        pool: str | None = None,
        cont: str | None = None,
        path: str | None = None,
    ) -> None:
        if path is not None:
            raise ValueError(
                'The mock DCont from PyDAOS does not support path. '
                'Use the pool and cont arguments instead.',
            )
        elif pool is None or cont is None:
            raise ValueError('Both pool and cont must be provided.')

        self._pool = pool
        self._cont = cont
        self._dobjs: dict[str, _DObj] = {}

    def __getitem__(self, name: str) -> _DObj:
        return self.get(name)

    def __str__(self) -> str:
        return f'{self._pool}/{self._cont}'

    def __repr__(self) -> str:
        return f'daos://{self._pool}/{self._cont}'

    def get(self, name: str) -> _DObj:
        """Get an object by name."""
        obj = self._dobjs.get(name, None)
        if obj is None:
            raise DObjNotFound(name)
        return obj

    def array(
        self,
        name: str,
        v: list[Any] | None = None,
        cid: str = '0',
    ) -> DArray:
        """Create a new DAOS array."""
        raise NotImplementedError

    def dict(
        self,
        name: str,
        v: dict[str, Any] | None = None,
        cid: str = '0',
    ) -> DDict:
        """Create a new DAOS dictionary."""
        dd = DDict(name)
        dd.bput(v)
        self._dobjs[name] = dd
        return dd


class _DObj:
    pass


class DArray(_DObj):
    """Class representing a DAOS array."""

    def __init__(self) -> None:
        raise NotImplementedError


class DDict(_DObj):
    """Class representing of DAOS dictionary.

    Currently, keys are strings and values are byte strings only.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.value_size = 1000 * 1000
        self._data: dict[str, bytes | None] = {}

    def __delitem__(self, key: str) -> None:
        self.put(key, None)

    def __getitem__(self, key: str) -> bytes:
        return self.get(key)

    def __setitem__(self, key: str, val: bytes) -> None:
        return self.put(key, val)

    def __len__(self) -> int:
        return len(self.dump())

    def __bool__(self) -> int:
        return len(self) > 0

    def __contains__(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, DDict):
            return False
        else:
            return self.dump() == other.dump()

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __iter__(self) -> Generator[str, None, None]:
        for key in self._data:
            if self._data[key] is not None:
                yield key

    def get(self, key: str) -> bytes:
        """Get a value by key."""
        val = self._data.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def put(self, key: str, val: bytes | None) -> None:
        """Put a value in the dictionary."""
        self.bput({key: val})

    def pop(self, key: str) -> None:
        """Remove a value from the dictionary."""
        self.put(key, None)

    def bget(
        self,
        d: dict[str, None] | None,
        value_size: int | None = None,
    ) -> dict[str, bytes] | None:
        """Bulk get values from the dictionary."""
        if d is None:
            return None
        d_ = cast(Dict[str, bytes | None], d)
        if value_size is None:
            value_size = self.value_size
        for k in d_:
            d_[k] = self.get(k)
        d__ = cast(Dict[str, bytes], d_)
        return d__

    def bput(self, d: dict[str, bytes | None] | None) -> None:
        """Bulk put values in the dictionary."""
        if d is None:
            return
        for k in d:
            self._data[k] = d[k]

    def dump(self) -> dict[str, bytes]:
        """Dump all key value pairs."""
        d = {k: None for k in self._data if self._data[k] is not None}
        res = self.bget(d)
        assert res is not None
        return res
