from __future__ import annotations

import pathlib

import pytest
from proxystore.connectors.file import FileConnector
from proxystore.connectors.local import LocalConnector
from proxystore.proxy import Proxy
from proxystore.store import register_store
from proxystore.store import Store
from proxystore.store import unregister_store
from proxystore.store.factory import StoreFactory

from proxystore_ex.plugins.distributed import Client
from proxystore_ex.plugins.distributed import proxy_task_wrapper
from proxystore_ex.plugins.distributed import pseudoproxy_by_size
from proxystore_ex.plugins.distributed import pseudoproxy_iterable
from proxystore_ex.plugins.distributed import pseudoproxy_mapping


def test_warn_unregistered_store() -> None:
    with Store('test_warn_unregistered_store', LocalConnector()) as store:
        with pytest.warns(UserWarning, match='Call register_store()'):
            client = Client(ps_store=store, ps_threshold=0)
            client.close()


def test_client_default_behavior() -> None:
    client = Client(n_workers=1, processes=False)

    future = client.submit(sum, [1, 2, 3])
    assert future.result() == 6

    futures = client.map(lambda x: x * x, [1, 2, 3])
    assert [f.result() for f in futures] == [1, 4, 9]

    futures = client.map(lambda x: x * x, [1, 2, 3], batch_size=2)
    assert [f.result() for f in futures] == [1, 4, 9]

    client.close()


def _square(x: int) -> int:
    assert isinstance(x, Proxy)
    return x * x


def test_client_proxy_everything(tmp_path: pathlib.Path) -> None:
    with Store(
        'test_client_proxy_everything',
        FileConnector(str(tmp_path / 'proxy-cache')),
    ) as store:
        register_store(store)

        client = Client(
            ps_store=store,
            ps_threshold=0,
            n_workers=1,
            processes=False,
        )

        future = client.submit(sum, [1, 2, 3])
        result = future.result()
        assert isinstance(result, Proxy)
        assert result == 6

        futures = client.map(_square, [1, 2, 3])
        results = [f.result() for f in futures]
        assert all([isinstance(r, Proxy) for r in results])
        assert results == [1, 4, 9]

        futures = client.map(_square, [1, 2, 3], batch_size=2)
        results = [f.result() for f in futures]
        assert all([isinstance(r, Proxy) for r in results])
        assert results == [1, 4, 9]

        client.close()

        unregister_store(store)


def test_client_proxy_skip_result(tmp_path: pathlib.Path) -> None:
    with Store(
        'test_client_proxy_skip_result',
        FileConnector(str(tmp_path / 'proxy-cache')),
    ) as store:
        register_store(store)

        client = Client(
            ps_store=store,
            ps_threshold=0,
            n_workers=1,
            processes=False,
        )

        future = client.submit(sum, [1, 2, 3], proxy_result=False)
        result = future.result()
        assert not isinstance(result, Proxy)
        assert result == 6

        client.close()

        unregister_store(store)


def test_pseudoproxy_by_size() -> None:
    test_obj = 'foobar'
    with Store('test_pseudoproxy_by_size', LocalConnector()) as store:
        # threshold = None should be a no-op and return the input object
        x = pseudoproxy_by_size(test_obj, store, None)
        assert x == test_obj

        def _factory() -> str:
            return test_obj

        # Passing a proxy should return its factory
        x = pseudoproxy_by_size(Proxy(_factory), store, 0)
        assert x == _factory
        assert x() == test_obj

        # Large threshold will not proxy object
        x = pseudoproxy_by_size(test_obj, store, int(1e6))
        assert x == test_obj

        # Object actually gets proxied here
        x = pseudoproxy_by_size(test_obj, store, 0, evict=True)
        assert isinstance(x, StoreFactory)
        assert store.exists(x.key)
        assert x() == test_obj
        assert not store.exists(x.key)


def test_pseudoproxy_iterable() -> None:
    with Store('test_pseudoproxy_iterable', LocalConnector()) as store:
        assert pseudoproxy_iterable([], store, 0) == ()

        assert pseudoproxy_iterable([1, 2, 3], store, None) == (1, 2, 3)

        x = pseudoproxy_iterable(['a', 'b', 'c'], store, 0)
        assert all([isinstance(v, StoreFactory) for v in x])

        v = ['x' * 10, 'x']
        x = pseudoproxy_iterable(v, store, 8)
        assert isinstance(x[0], StoreFactory)
        assert isinstance(x[1], str)


def test_pseudoproxy_mapping() -> None:
    with Store('test_pseudoproxy_mapping', LocalConnector()) as store:
        assert pseudoproxy_mapping({}, store, 0) == {}

        m = {'a': 1, 'b': 2}
        assert pseudoproxy_mapping(m, store, None) == m

        x = pseudoproxy_mapping({'a': 'a', 'b': 'b'}, store, 0)
        assert all([isinstance(v, StoreFactory) for v in x.values()])

        v = {'a': 'x' * 10, 'b': 'x'}
        x = pseudoproxy_mapping(v, store, 8)
        assert isinstance(x['a'], StoreFactory)
        assert isinstance(x['b'], str)


def test_proxy_task_wrapper() -> None:
    with Store('test_proxy_task_wrapper', LocalConnector()) as store:

        def _foo(a: int, b: str, *, c: int, d: str) -> str:
            assert not isinstance(a, Proxy)
            assert isinstance(b, Proxy)
            assert not isinstance(c, Proxy)
            assert isinstance(d, Proxy)

            return str(a) + b + str(c) + d

        foo = proxy_task_wrapper(_foo, store, threshold=8, evict=True)

        b = store.proxy('b' * 10, evict=True).__factory__
        d = store.proxy('d' * 10, evict=True).__factory__

        result = foo(1, b, c=2, d=d)

        assert isinstance(result, StoreFactory)
        assert result() == '1bbbbbbbbbb2dddddddddd'
        assert not store.exists(result.key)


def test_proxy_task_wrapper_standard() -> None:
    with Store('test_proxy_task_wrapper_standard', LocalConnector()) as store:

        def _foo(x: int, *, y: int) -> int:
            return x * y

        foo = proxy_task_wrapper(_foo, store)

        assert foo(2, y=3) == 6
