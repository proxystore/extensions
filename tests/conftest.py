from __future__ import annotations

import sys
from collections.abc import Generator

try:
    import pydaos
except ImportError:
    from testing.mocked import pydaos

    sys.modules['pydaos'] = pydaos

try:
    import pymargo
except ImportError:
    from testing.mocked import pymargo

    sys.modules['pymargo'] = pymargo
    sys.modules['pymargo.bulk'] = pymargo
    sys.modules['pymargo.core'] = pymargo

try:
    import ucp
except ImportError:
    from testing.mocked import ucp

    sys.modules['ucp'] = ucp

import proxystore
import proxystore.store
import pytest


@pytest.fixture(autouse=True)
def _verify_no_registered_stores() -> Generator[None, None, None]:
    yield

    if len(proxystore.store._stores) > 0:  # pragma: no cover
        raise RuntimeError(
            'Test left at least one store registered: '
            f'{tuple(proxystore.store._stores.keys())}.',
        )
