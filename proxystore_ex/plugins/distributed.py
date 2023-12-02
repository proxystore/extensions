"""Custom ProxyStore client for Dask Distributed."""
from __future__ import annotations

import copyreg
import functools
import sys
import warnings
from functools import partial
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import NoReturn
from typing import TypeVar

if sys.version_info >= (3, 10):  # pragma: >3.10 cover
    from typing import ParamSpec
else:  # pragma: <3.10 cover
    from typing_extensions import ParamSpec

import cloudpickle
from dask.base import normalize_token
from dask.base import tokenize
from dask.utils import funcname
from distributed import Client as DaskDistributedClient
from distributed import Future
from distributed.protocol import dask_deserialize
from distributed.protocol import dask_serialize
from proxystore.proxy import _proxy_trampoline
from proxystore.proxy import FactoryType
from proxystore.proxy import Proxy
from proxystore.serialize import deserialize
from proxystore.serialize import serialize
from proxystore.store import get_store
from proxystore.store import Store
from proxystore.store.utils import get_key
from proxystore.store.utils import resolve_async

T = TypeVar('T')
P = ParamSpec('P')


def _proxy_reduce(
    proxy: Proxy[T],
) -> tuple[Callable[[FactoryType[T]], Proxy[T]], tuple[FactoryType[T]]]:
    return _proxy_trampoline, (object.__getattribute__(proxy, '__factory__'),)


cloudpickle.Pickler.dispatch_table[Proxy] = _proxy_reduce
copyreg.pickle(Proxy, _proxy_reduce)


@dask_serialize.register(Proxy)
def _serialize_proxy(proxy: Proxy[Any]) -> tuple[dict[str, Any], list[bytes]]:
    frames = [serialize(proxy)]
    return {}, frames


@dask_deserialize.register(Proxy)
def _deserialize_proxy(
    header: dict[str, Any],
    frames: list[bytes],
) -> Proxy[Any]:
    return deserialize(frames[0])


@normalize_token.register(Proxy)
def _normalize_proxy(p: Proxy[Any]) -> NoReturn:
    # TODO: return custom type (e.g., Proxy(Factory(...))).
    raise TypeError('Token normalization not support on Proxy types.')


class Client(DaskDistributedClient):
    """Dask Distributed Client with ProxyStore support.

    This is a wrapper around [`dask.distributed.Client`][distributed.Client]
    that proxies function arguments and return values using a provided
    [`Store`][proxystore.store.base.Store] and threshold size.

    Args:
        args: Positional arguments to pass to
            [`dask.distributed.Client`][distributed.Client].
        ps_store: Store to use when proxying objects.
        ps_threshold: Object size threshold in bytes. Objects larger than this
            threshold will be proxied.
        kwargs: Keyword arguments to pass to
            [`dask.distributed.Client`][distributed.Client].
    """

    def __init__(
        self,
        *args: Any,
        ps_store: Store[Any] | None = None,
        ps_threshold: int = 100_000,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        if ps_store is not None and get_store(ps_store.name) is None:
            warnings.warn(
                f'The store instance named "{ps_store.name}" has not been '
                'registered. This may result in two copies of the store '
                'being initialized on this process. Call register_store() '
                'before instantiating the Client.',
                stacklevel=2,
            )

        self._ps_store = ps_store
        self._ps_threshold = ps_threshold

    def map(  # type: ignore[no-untyped-def]
        self,
        func,
        *iterables,
        key=None,
        workers=None,
        retries=None,
        resources=None,
        priority=0,
        allow_other_workers=False,
        fifo_timeout='100 ms',
        actor=False,
        actors=False,
        pure=True,
        batch_size=None,
        proxy_args: bool = True,
        proxy_result: bool = True,
        **kwargs,
    ):
        """Map a function on a sequence of arguments.

        This has the same behavior as [`Client.map()`][distributed.Client.map]
        but arguments and return values larger than the ProxyStore threshold
        size will be passed-by-proxy.

        This method adds the `proxy_args` and `proxy_result` flags (default
        `True`) which can be used to disable proxying of function arguments
        or return values, respectively, for a single invocation.

        Note:
            Proxied arguments will be evicted from the store when the
            future containing the result of the function application is set.
        """
        total_length = sum(len(x) for x in iterables)
        if (
            not (batch_size and batch_size > 1 and total_length > batch_size)
            and self._ps_store is not None
        ):
            # map() partitions the iterators if batching needs to be performed
            # and calls itself again on each of the batches in the iterators.
            # In this case, we don't want to proxy the pre-batched iterators
            # and instead want to wait to proxy until the later calls to map()
            # on each batch.
            if proxy_args:
                key = key or funcname(func)
                iterables = list(zip(*zip(*iterables)))  # type: ignore[assignment]
                if not isinstance(key, list) and pure:
                    # Calling tokenize() on args/kwargs containing proxies will
                    # fail because the tokenize dispatch mechanism will perform
                    # introspection on the proxy. To avoid this failure, we
                    # can create the key before proxying. Source:
                    # https://github.com/dask/distributed/blob/6d1e1333a72dd78811883271511070c70369402b/distributed/client.py#L2126
                    key = [
                        f'{key}-{tokenize(func, kwargs, *args)}-proxy'
                        for args in zip(*iterables)
                    ]

                iterables = tuple(
                    proxy_iterable(
                        iterable,
                        store=self._ps_store,
                        threshold=self._ps_threshold,
                        evict=False,
                    )
                    for iterable in iterables
                )

                kwargs = proxy_mapping(
                    kwargs,
                    store=self._ps_store,
                    threshold=self._ps_threshold,
                    evict=False,
                )

            if proxy_result:
                func = wrap_proxy_result(
                    func,
                    store=self._ps_store,
                    threshold=self._ps_threshold,
                    evict=True,
                )

        futures = super().map(
            func,
            *iterables,
            key=key,
            workers=workers,
            retries=retries,
            resources=resources,
            priority=priority,
            allow_other_workers=allow_other_workers,
            fifo_timeout=fifo_timeout,
            actor=actor,
            actors=actors,
            pure=pure,
            batch_size=batch_size,
            **kwargs,
        )

        if self._ps_store is not None and proxy_args:
            for future, *args in zip(futures, *iterables):
                proxied_args = [v for v in args if isinstance(v, Proxy)]
                callback = partial(
                    _evict_proxies_callback,
                    proxies=proxied_args,
                    store=self._ps_store,
                )
                future.add_done_callback(callback)

        return futures

    def submit(  # type: ignore[no-untyped-def]
        self,
        func,
        *args,
        key=None,
        workers=None,
        resources=None,
        retries=None,
        priority=0,
        fifo_timeout='100 ms',
        allow_other_workers=False,
        actor=False,
        actors=False,
        pure=True,
        proxy_args: bool = True,
        proxy_result: bool = True,
        **kwargs,
    ):
        """Submit a function application to the scheduler.

        This has the same behavior as
        [`Client.submit()`][distributed.Client.submit] but arguments and
        return values larger than the ProxyStore threshold size will be
        passed-by-proxy.

        This method adds the `proxy_args` and `proxy_result` flags (default
        `True`) which can be used to disable proxying of function arguments
        or return values, respectively, for a single invocation.

        Note:
            Proxied arguments will be evicted from the store when the
            future containing the result of the function application is set.
        """
        proxied_args: list[Proxy[Any]] = []
        if self._ps_store is not None and proxy_args:
            if key is None and pure:
                # Calling tokenize() on args/kwargs containing proxies will
                # fail because the tokenize dispatch mechanism will perform
                # introspection on the proxy. To avoid this failure, we
                # can create the key before proxying. Source:
                # https://github.com/dask/distributed/blob/6d1e1333a72dd78811883271511070c70369402b/distributed/client.py#L1942
                key = f'{funcname(func)}-{tokenize(func, kwargs, *args)}-proxy'

            args = proxy_iterable(
                args,
                store=self._ps_store,
                threshold=self._ps_threshold,
                # Don't evict data after proxy resolve because we will
                # manually evict after the task future completes.
                evict=False,
            )
            proxied_args.extend(v for v in args if isinstance(v, Proxy))

            kwargs = proxy_mapping(
                kwargs,
                store=self._ps_store,
                threshold=self._ps_threshold,
                evict=False,
            )
            proxied_args.extend(
                v for v in kwargs.values() if isinstance(v, Proxy)
            )

        if self._ps_store is not None and proxy_result:
            func = wrap_proxy_result(
                func,
                store=self._ps_store,
                threshold=self._ps_threshold,
                evict=True,
            )

        future = super().submit(
            func,
            *args,
            key=key,
            workers=workers,
            resources=resources,
            retries=retries,
            priority=priority,
            fifo_timeout=fifo_timeout,
            allow_other_workers=allow_other_workers,
            actor=actor,
            actors=actors,
            pure=pure,
            **kwargs,
        )

        if len(proxied_args) > 0:
            callback = partial(
                _evict_proxies_callback,
                proxies=proxied_args,
                store=self._ps_store,
            )
            future.add_done_callback(callback)

        return future


def _evict_proxies_callback(
    future: Future[Any],
    proxies: Iterable[Proxy[Any]],
    store: Store[Any],
) -> None:
    for proxy in proxies:
        store.evict(get_key(proxy))

    result = future.result()
    if isinstance(result, Proxy):
        resolve_async(result)
        # TODO: should we evict here?


def _serialize_and_proxy(
    x: T,
    store: Store[Any],
    threshold: int,
    evict: bool = True,
) -> T | Proxy[T]:
    s = serialize(x)

    if len(s) >= threshold:
        res = store.proxy(
            s,
            evict=evict,
            serializer=lambda x: x,
            skip_nonproxiable=True,
        )
        # Hack to avoid needlessly resolving this proxy on the current process.
        # This is likely to occur when Dask tries to serialize the task
        # payload containing this proxy. Dask uses cloudpickle, and cloudpickle
        # inspect the type of objects being serialized which will trigger
        # a proxy resolve. This hack has no overhead because it's just a
        # reference to the original object, and when the proxy is serialized
        # the target will not be included.
        res.__target__ = x
    else:
        # In this case, we paid the cost of serializing x but did not use
        # that serialization of x so it will be serialized again using
        # Dask's mechanisms. This adds some overhead, but the hope is that
        # the threshold is reasonably set such that it is only small objects
        # which get serialized twice. Large objects above the threshold only
        # get serialized once by ProxyStore and the lightweight proxy is
        # serialized by Dask.
        res = x

    return res


def proxy_iterable(
    i: Iterable[Any],
    store: Store[Any],
    threshold: int,
    evict: bool = True,
) -> tuple[Any]:
    """Proxy values in an iterable than the threshold size.

    Args:
        i: Iterable containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Tuple containing the objects yielded by the iterable with objects
        larger than the threshold size replaced with proxies.
    """
    return tuple(
        _serialize_and_proxy(v, store=store, threshold=threshold, evict=evict)
        for v in i
    )


def proxy_mapping(
    m: Mapping[T, Any],
    store: Store[Any],
    threshold: int,
    evict: bool = True,
) -> dict[T, Any]:
    """Proxy values in a mapping larger than the threshold size.

    Args:
        m: Mapping containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Mapping containing the same keys and values as the input mapping
        but objects larger than the threshold size are replaced with proxies.
    """
    return {
        k: _serialize_and_proxy(
            m[k],
            store=store,
            threshold=threshold,
            evict=evict,
        )
        for k in m
    }


def wrap_proxy_result(
    func: Callable[P, T],
    store: Store[Any],
    threshold: int,
    evict: bool = True,
) -> Callable[P, T | Proxy[T]]:
    """Wrap a function to proxies return values larger than a threshold size.

    Args:
        func: Function to wrap.
        store: Store to use to proxy the result.
        threshold: Threshold size in bytes.
        evict: Evict flag value to pass to the created proxy.

    Returns:
        Callable with the same shape as `func` but that returns either the
        original return type or a proxy of the return type.
    """

    @functools.wraps(func)
    def _proxy_wrapper(*args: P.args, **kwargs: P.kwargs) -> T | Proxy[T]:
        result = func(*args, **kwargs)
        proxy_or_result = _serialize_and_proxy(
            result,
            store=store,
            threshold=threshold,
            evict=evict,
        )
        return proxy_or_result

    return _proxy_wrapper
