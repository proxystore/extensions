"""ProxyStore extensions package."""
from __future__ import annotations

import sys

if sys.version_info >= (3, 8):  # pragma: >=3.8 cover
    import importlib.metadata as importlib_metadata
else:  # pragma: <3.8 cover
    import importlib_metadata


__version__ = importlib_metadata.version('proxystore_extensions')
