from __future__ import annotations

import contextlib
import importlib.util
import platform
from typing import Any
from typing import Callable
from typing import ContextManager
from typing import Generator
from unittest import mock

import pytest

try:
    from proxystore.connectors.connector import Connector
except ImportError:  # pragma: no cover
    # This import changed in ProxyStore v0.6.1
    from proxystore.connectors.protocols import Connector

from proxystore_ex.connectors.daos import DAOSConnector
from proxystore_ex.connectors.dim import margo
from proxystore_ex.connectors.dim import ucx
from proxystore_ex.connectors.dim import zmq
from testing.mocked.pydaos import DCont as MockDCont
from testing.mocked.pydaos import DDict as MockDDict
from testing.mocking import mock_multiprocessing
from testing.utils import open_port

FIXTURE_LIST = [
    'daos_connector',
    'margo_connector',
    'ucx_connector',
    'zmq_connector',
]


@pytest.fixture(scope='session')
def daos_connector() -> Generator[Connector[Any], None, None]:
    """Mocked DAOS connector fixture."""
    with mock.patch('pydaos.DCont', MockDCont), mock.patch(
        'pydaos.DDict',
        MockDDict,
    ):
        connector = DAOSConnector(
            pool='test-pool',
            container='test-container',
            namespace='test-namespace',
        )

    yield connector

    connector.close()


@pytest.fixture(scope='session')
def margo_connector() -> Generator[Connector[Any], None, None]:
    """MargoConnector fixture."""
    port = open_port()
    protocol = margo.Protocol.OFI_TCP

    margo_spec = importlib.util.find_spec('pymargo')

    ctx: Callable[[], ContextManager[None]] = contextlib.nullcontext
    timeout = 1.0
    if (  # pragma: no branch
        margo_spec is not None and 'mocked' in margo_spec.name
    ):
        ctx = mock_multiprocessing
        timeout = 0.01

    with ctx():
        connector = margo.MargoConnector(
            protocol=protocol,
            port=port,
            timeout=timeout,
            force_spawn_server=True,
        )

    yield connector

    with ctx():
        connector.close()


@pytest.fixture(scope='session')
def ucx_connector() -> Generator[Connector[Any], None, None]:
    """UCXConnector fixture."""
    port = open_port()

    ucp_spec = importlib.util.find_spec('ucp')

    ctx: Callable[[], ContextManager[None]] = contextlib.nullcontext
    if ucp_spec is not None and 'mocked' in ucp_spec.name:  # pragma: no branch
        ctx = mock_multiprocessing

    with ctx():
        connector = ucx.UCXConnector(port=port)

    yield connector

    with ctx():
        connector.close()

    if (
        ucp_spec is not None and 'mocked' not in ucp_spec.name
    ):  # pragma: no cover
        connector._loop.run_until_complete(ucx.reset_ucp_async())


@pytest.fixture(scope='session')
def zmq_connector() -> Generator[Connector[Any], None, None]:
    """ZeroMQ store fixture."""
    port = open_port()

    # MacOS GitHub Actions runners are slow
    timeout = 1.0 if platform.system() == 'Darwin' else 0.5

    with zmq.ZeroMQConnector(
        port=port,
        timeout=timeout,
    ) as connector:
        yield connector


@pytest.fixture(scope='session', params=FIXTURE_LIST)
def connectors(request) -> Generator[Connector[Any], None, None]:
    """Parameterized fixture that returns all Connector implementations."""
    connector = request.getfixturevalue(request.param)

    with mock.patch.object(
        connector,
        'close',
        side_effect=RuntimeError(
            'Tests using connectors fixtures should not call '
            'close() on the yielded connector instance.',
        ),
    ):
        yield connector
