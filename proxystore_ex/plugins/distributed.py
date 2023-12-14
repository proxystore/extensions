"""Custom ProxyStore client for Dask Distributed."""
from __future__ import annotations

import functools
import logging
import sys
import warnings
from functools import partial
from typing import Any
from typing import Callable
from typing import cast
from typing import Iterable
from typing import Mapping
from typing import TypeVar

if sys.version_info >= (3, 10):  # pragma: >3.10 cover
    from typing import ParamSpec
else:  # pragma: <3.10 cover
    from typing_extensions import ParamSpec

from dask.base import tokenize
from dask.utils import funcname
from distributed import Client as DaskDistributedClient
from distributed import Future as DaskDistributedFuture
from proxystore.connectors.protocols import Connector
from proxystore.proxy import _proxy_trampoline
from proxystore.proxy import Proxy
from proxystore.serialize import serialize
from proxystore.store import get_store
from proxystore.store import Store
from proxystore.store.factory import StoreFactory
from proxystore.store.types import ConnectorKeyT

T = TypeVar('T')
P = ParamSpec('P')
ConnectorT = TypeVar('ConnectorT', bound=Connector[Any])

logger = logging.getLogger(__name__)


class Future(DaskDistributedFuture):
    """Custom future which returns results as proxies as necessary.

    The ProxyStore Dask [`Client`][proxystore_ex.plugins.distributed.Client]
    can return large function results as a
    [`StoreFactory`][proxystore.store.factory.StoreFactory] instance which
    will return the actual function result when invoked. This custom
    Dask [`Future`][distributed.Future] will wrap result factories in a
    [`Proxy`][proxystore.proxy.Proxy].
    """

    def result(self, timeout: int | None = None) -> Any:
        """Wait until computation completes, gather result to local process."""
        result = super().result()
        if isinstance(result, StoreFactory):
            result = _proxy_trampoline(result)
        return result


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

        Warning:
            Unless the function is explicitly marked as not pure, a function
            result that gets proxied will not be automatically evicted. This
            is because Dask caches results of pure functions to avoid
            duplicate computation so it is not guaranteed to be safe to evict
            the function result once consumed by the client code.
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

            key = key or funcname(func)
            iterables = list(zip(*zip(*iterables)))  # type: ignore[assignment]
            if not isinstance(key, list) and pure:  # pragma: no branch
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
                pseudoproxy_iterable(
                    iterable,
                    store=self._ps_store,
                    threshold=self._ps_threshold if proxy_args else None,
                    evict=False,
                )
                for iterable in iterables
            )

            kwargs = pseudoproxy_mapping(
                kwargs,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_args else None,
                evict=False,
            )

            func = proxy_task_wrapper(
                func,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_result else None,
                # Pure function results can be cached so we don't want to
                # evict those once the result is consumed
                evict=not pure,
            )

        base_futures = super().map(
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

        if (
            not (batch_size and batch_size > 1 and total_length > batch_size)
            and self._ps_store is not None
        ):
            futures = [
                Future(
                    key=base_future.key,
                    client=base_future._client,
                    inform=base_future._inform,
                    state=base_future._state,
                )
                for base_future in base_futures
            ]
            del base_futures

            for future, *args in zip(futures, *iterables):
                proxied_args_keys = [
                    f.key for f in args if isinstance(f, StoreFactory)
                ]
                # TODO: how to delete kwargs?
                callback = partial(
                    _evict_proxies_callback,
                    keys=proxied_args_keys,
                    store=self._ps_store,
                )
                future.add_done_callback(callback)

            return futures
        else:
            return base_futures

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

        Warning:
            Unless the function is explicitly marked as not pure, a function
            result that gets proxied will not be automatically evicted. This
            is because Dask caches results of pure functions to avoid
            duplicate computation so it is not guaranteed to be safe to evict
            the function result once consumed by the client code.
        """
        proxied_args_keys: list[ConnectorKeyT] = []
        if self._ps_store is not None:
            if key is None and pure:  # pragma: no branch
                # Calling tokenize() on args/kwargs containing proxies will
                # fail because the tokenize dispatch mechanism will perform
                # introspection on the proxy. To avoid this failure, we
                # can create the key before proxying. Source:
                # https://github.com/dask/distributed/blob/6d1e1333a72dd78811883271511070c70369402b/distributed/client.py#L1942
                key = f'{funcname(func)}-{tokenize(func, kwargs, *args)}-proxy'
                pure = False

            args = pseudoproxy_iterable(
                args,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_args else None,
                # Don't evict data after proxy resolve because we will
                # manually evict after the task future completes.
                evict=False,
            )
            proxied_args_keys.extend(
                f.key for f in args if isinstance(f, StoreFactory)
            )

            kwargs = pseudoproxy_mapping(
                kwargs,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_args else None,
                evict=False,
            )
            proxied_args_keys.extend(
                f.key for f in kwargs.values() if isinstance(f, StoreFactory)
            )

            func = proxy_task_wrapper(
                func,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_result else None,
                # Pure function results can be cached so we don't want to
                # evict those once the result is consumed
                evict=not pure,
            )

        base_future = super().submit(
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

        if self._ps_store is not None:
            future = Future(
                key=base_future.key,
                client=base_future._client,
                inform=base_future._inform,
                state=base_future._state,
            )
            del base_future

            callback = partial(
                _evict_proxies_callback,
                keys=proxied_args_keys,
                store=self._ps_store,
            )
            future.add_done_callback(callback)

            return future
        else:
            return base_future


def _evict_proxies_callback(
    _future: Future,
    keys: Iterable[ConnectorKeyT],
    store: Store[Any],
) -> None:
    for key in keys:
        store.evict(key)


def pseudoproxy_by_size(
    x: T | Proxy[T],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> T | StoreFactory[ConnectorT, T]:
    """Serialize an object and proxy it if the object is larger enough.

    Args:
        x: Object to possibly proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, the object will not
            be proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        The input object `x` if `x` is smaller than `threshold` otherwise
        a [`StoreFactory`][proxystore.store.factory.StoreFactory] which can
        be used to initialize a [`Proxy`][proxystore.proxy.Proxy].
    """
    if threshold is None:
        return x

    if isinstance(x, Proxy):
        # Shortcut to replace proxies with their factories because
        # proxies are not compatible with Dask as function arguments.
        return x.__factory__

    s = serialize(x)

    if len(s) >= threshold:
        proxy = store.proxy(
            s,
            evict=evict,
            serializer=lambda x: x,
            skip_nonproxiable=True,
        )
        res = proxy.__factory__
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


def pseudoproxy_iterable(
    iterable: Iterable[Any],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> tuple[Any, ...]:
    """Psuedoproxy values in an iterable than the threshold size.

    This function is "pseudo" because values larger than the threshold size
    are technically proxied, but the proxies are discarded and only the
    internal factory is returned. This is because Dask does not play nicely
    with serializing proxy types so we pass the factories instead and
    reconstruct the proxies later.

    Args:
        iterable: Iterable containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, no objects will b
            proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Tuple containing the objects yielded by the iterable with objects
        larger than the threshold size replaced with factories which
        can later be used to construct proxies.
    """
    if threshold is None:
        return tuple(iterable)

    return tuple(
        pseudoproxy_by_size(
            value,
            store=store,
            threshold=threshold,
            evict=evict,
        )
        for value in iterable
    )


def pseudoproxy_mapping(
    mapping: Mapping[T, Any],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> dict[T, Any]:
    """Psuedoproxy values in a mapping larger than the threshold size.

    This function is "pseudo" because values larger than the threshold size
    are technically proxied, but the proxies are discarded and only the
    internal factory is returned. This is because Dask does not play nicely
    with serializing proxy types so we pass the factories instead and
    reconstruct the proxies later.

    Args:
        mapping: Mapping containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, no objects will b
            proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Mapping containing the same keys and values as the input mapping
        but objects larger than the threshold size are replaced with factories
        which can be later used to construct proxies.
    """
    if threshold is None:
        return dict(mapping)

    return {
        key: pseudoproxy_by_size(
            mapping[key],
            store=store,
            threshold=threshold,
            evict=evict,
        )
        for key in mapping
    }


def proxy_task_wrapper(
    func: Callable[P, T],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> Callable[P, T | StoreFactory[ConnectorT, T]]:
    """Proxy task wrapper.

    Wraps a task function with mechanisms to translate StoreFactory types
    to Proxy types initialized with the factory and to proxy return
    values larger than a threshold.

    Args:
        func: Function to wrap.
        store: Store to use to proxy the result.
        threshold: Threshold size in bytes.
        evict: Evict flag value to pass to the created proxy.

    Returns:
        Callable with the same shape as `func` but that returns either the
        original return type or a factory of the return type which can be
        used to construct a proxy.
    """

    @functools.wraps(func)
    def _proxy_wrapper(
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T | StoreFactory[ConnectorT, T]:
        args = cast(
            P.args,
            tuple(
                _proxy_trampoline(v) if isinstance(v, StoreFactory) else v
                for v in args
            ),
        )
        kwargs = cast(
            P.kwargs,
            {
                k: _proxy_trampoline(v) if isinstance(v, StoreFactory) else v
                for k, v in kwargs.items()
            },
        )

        result = func(*args, **kwargs)
        factory_or_result = pseudoproxy_by_size(
            result,
            store=store,
            threshold=threshold,
            evict=evict,
        )
        return factory_or_result

    return _proxy_wrapper
