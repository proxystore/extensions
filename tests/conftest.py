from __future__ import annotations

import sys

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

from testing.connectors import connectors
from testing.connectors import daos_connector
from testing.connectors import margo_connector
from testing.connectors import ucx_connector
from testing.connectors import zmq_connector
