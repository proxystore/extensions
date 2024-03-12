"""Extensions for ProxyStore.

!!! tip

    Extension features can be imported directly. E.g.,
    ```python
    from proxystore_ex.connectors.daos import DAOSConnector
    ```
    But we recommend replacing `proxystore_ex` with `proxystore.ex`. E.g.,
    ```python
    from proxystore.ex.connectors.daos import DAOSConnector
    ```
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import sys

__version__ = importlib_metadata.version('proxystore_ex')
