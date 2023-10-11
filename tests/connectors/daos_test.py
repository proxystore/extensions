from __future__ import annotations

import uuid
from typing import Generator
from unittest import mock

import pytest

from proxystore_ex.connectors.daos import DAOSConnector
from proxystore_ex.connectors.daos import DAOSKey
from testing.mocked.pydaos import DCont as MockDCont
from testing.mocked.pydaos import DDict as MockDDict


@pytest.fixture()
def connector() -> Generator[DAOSConnector, None, None]:
    with mock.patch('pydaos.DCont', MockDCont), mock.patch(
        'pydaos.DDict',
        MockDDict,
    ):
        with DAOSConnector(
            pool=str(uuid.uuid4()),
            container=str(uuid.uuid4()),
            namespace=str(uuid.uuid4()),
        ) as connector:
            yield connector


def test_options_validate_key(connector: DAOSConnector) -> None:
    fake_key = DAOSKey(
        pool=str(uuid.uuid4()),
        container=str(uuid.uuid4()),
        namespace=str(uuid.uuid4()),
        dict_key=str(uuid.uuid4()),
    )

    with pytest.raises(ValueError, match='key do not match the connector'):
        connector.evict(fake_key)

    with pytest.raises(ValueError, match='key do not match the connector'):
        connector.exists(fake_key)

    with pytest.raises(ValueError, match='key do not match the connector'):
        connector.get(fake_key)

    with pytest.raises(ValueError, match='key do not match the connector'):
        connector.get_batch([fake_key])


def test_clear(connector: DAOSConnector) -> None:
    key = connector.put(b'value')
    connector.close(clear=True)
    assert connector.get(key) is None
