from __future__ import annotations

import pathlib

import pytest
from proxystore.connectors.file import FileConnector
from proxystore.connectors.local import LocalConnector
from proxystore.proxy import Proxy
from proxystore.store import Store
from proxystore.store.utils import get_key

from proxystore_ex.plugins.distributed import Client
from proxystore_ex.plugins.distributed import proxy_by_size
from proxystore_ex.plugins.distributed import proxy_iterable
from proxystore_ex.plugins.distributed import proxy_mapping
from proxystore_ex.plugins.distributed import proxy_task_wrapper


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
        register=True,
    ) as store:
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


def test_client_proxy_skip_result(tmp_path: pathlib.Path) -> None:
    with Store(
        'test_client_proxy_skip_result',
        FileConnector(str(tmp_path / 'proxy-cache')),
        register=True,
    ) as store:
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


def _pow(x: int, *, p: int) -> int:
    assert isinstance(x, Proxy)
    assert isinstance(p, Proxy)
    return x**p


def test_client_map_proxy_kwarg_warning(tmp_path: pathlib.Path) -> None:
    with Store(
        'test_client_map_proxy_kwarg_warning',
        FileConnector(str(tmp_path / 'proxy-cache')),
        register=True,
    ) as store:
        client = Client(
            ps_store=store,
            ps_threshold=0,
            n_workers=1,
            processes=False,
        )

        with pytest.warns(UserWarning):
            futures = client.map(_pow, [1, 2, 3], p=2)

        results = [f.result() for f in futures]
        assert all([isinstance(r, Proxy) for r in results])
        assert results == [1, 4, 9]

        client.close()


def test_client_submit_manual_proxy(tmp_path: pathlib.Path) -> None:
    with Store(
        'test_client_submit_manual_proxy',
        FileConnector(str(tmp_path / 'proxy-cache')),
        register=True,
    ) as store:
        client = Client(
            ps_store=store,
            ps_threshold=int(1e6),
            n_workers=1,
            processes=False,
        )

        x = store.proxy([1, 2, 3])

        future = client.submit(sum, x, key='test-client-submit-manual-proxy')
        assert future.result() == 6

        client.close()


def test_proxy_by_size() -> None:
    test_obj = 'foobar'
    with Store('test_proxy_by_size', LocalConnector(), register=True) as store:
        # threshold = None should be a no-op and return the input object
        x = proxy_by_size(test_obj, store, None)
        assert x == test_obj

        def _factory() -> str:
            return test_obj

        # Passing a proxy should return the proxy
        p = Proxy(_factory)
        x = proxy_by_size(p, store, 0)
        assert x == p

        # Large threshold will not proxy object
        x = proxy_by_size(test_obj, store, int(1e6))
        assert x == test_obj

        # Object actually gets proxied here
        x = proxy_by_size(test_obj, store, 0, evict=True)
        assert isinstance(x, Proxy)
        # The target is already set by default
        del x.__proxy_target__
        assert x == test_obj
        assert not store.exists(get_key(x))


def test_proxy_iterable() -> None:
    with Store(
        'test_proxy_iterable',
        LocalConnector(),
        register=True,
    ) as store:
        assert proxy_iterable([], store, 0) == ()

        assert proxy_iterable([1, 2, 3], store, None) == (1, 2, 3)

        x = proxy_iterable(['a', 'b', 'c'], store, 0)
        assert all([isinstance(v, Proxy) for v in x])

        v = ['x' * 10, 'x']
        x = proxy_iterable(v, store, 8)
        assert isinstance(x[0], Proxy)
        assert isinstance(x[1], str)


def test_proxy_mapping() -> None:
    with Store('test_proxy_mapping', LocalConnector(), register=True) as store:
        assert proxy_mapping({}, store, 0) == {}

        m = {'a': 1, 'b': 2}
        assert proxy_mapping(m, store, None) == m

        x = proxy_mapping({'a': 'a', 'b': 'b'}, store, 0)
        assert all([isinstance(v, Proxy) for v in x.values()])

        v = {'a': 'x' * 10, 'b': 'x'}
        x = proxy_mapping(v, store, 8)
        assert isinstance(x['a'], Proxy)
        assert isinstance(x['b'], str)


def test_proxy_task_wrapper() -> None:
    with Store(
        'test_proxy_task_wrapper',
        LocalConnector(),
        register=True,
    ) as store:

        def _foo(a: int, b: str, *, c: int, d: str) -> str:
            assert not isinstance(a, Proxy)
            assert isinstance(b, Proxy)
            assert not isinstance(c, Proxy)
            assert isinstance(d, Proxy)

            return str(a) + b + str(c) + d

        foo = proxy_task_wrapper(_foo, store, threshold=8, evict=True)

        b = store.proxy('b' * 10, evict=True)
        d = store.proxy('d' * 10, evict=True)

        result = foo(1, b, c=2, d=d)

        assert isinstance(result, Proxy)
        # The target is already set by default
        del result.__proxy_target__
        assert result == '1bbbbbbbbbb2dddddddddd'
        assert not store.exists(get_key(result))


def test_proxy_task_wrapper_standard() -> None:
    with Store(
        'test_proxy_task_wrapper_standard',
        LocalConnector(),
        register=True,
    ) as store:

        def _foo(x: int, *, y: int) -> int:
            return x * y

        foo = proxy_task_wrapper(_foo, store)

        assert foo(2, y=3) == 6
