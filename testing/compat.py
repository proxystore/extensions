from __future__ import annotations

import random


def randbytes(size: int) -> bytes:
    """Get random byte string of specified size.

    This used to be for Python <=3.8 compatibility where it
    used `random.randbytes()` in Python 3.9 or newer and
    `os.urandom()` in Python 3.8 and older. We no longer support
    those versions but we keep for compatibility.

    Args:
        size: The size of byte string to return.

    Returns:
        A random byte string.
    """
    return random.randbytes(size)
