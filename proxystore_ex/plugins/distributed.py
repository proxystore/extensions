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

try:
    from dask.base import tokenize
    from dask.utils import funcname
    from distributed import Client as DaskDistributedClient
    from distributed import Future as DaskDistributedFuture
except ImportError as e:  # pragma: no cover
    raise ImportError(
        'The dask and distributed packages must both be installed to '
        'use the associated plugins.',
    ) from e

from proxystore.connectors.protocols import Connector
from proxystore.proxy import Proxy
from proxystore.serialize import serialize
from proxystore.store import get_or_create_store
from proxystore.store import get_store
from proxystore.store import Store
from proxystore.store.types import ConnectorKeyT
from proxystore.store.utils import get_key
from proxystore.warnings import ExperimentalWarning

warnings.warn(
    'Dask plugins are an experimental feature and may exhibit unexpected '
    'behaviour or change in the future.',
    category=ExperimentalWarning,
    stacklevel=2,
)

T = TypeVar('T')
P = ParamSpec('P')
ConnectorT = TypeVar('ConnectorT', bound=Connector[Any])

logger = logging.getLogger(__name__)


class Client(DaskDistributedClient):
    """Dask Distributed Client with ProxyStore support.

    This is a wrapper around [`dask.distributed.Client`][distributed.Client]
    that proxies function arguments and return values using a provided
    [`Store`][proxystore.store.base.Store] and threshold size.

    !!! warning

        The custom Dask [`Client`][proxystore_ex.plugins.distributed.Client]
        is an experimental feature and the API may change in the future. If you
        encounter unexpected behavior, please
        [open a bug report](https://github.com/proxystore/extensions/issues/new/choose){target=_blank}.

    Using this custom client is as easy as changing your import and passing
    two extra arguments to the constructor.

    ```python linenums="1" title="example.py" hl_lines="3 9"
    import tempfile

    from proxystore.ex.plugins.distributed import Client  # (1)!
    from proxystore.connectors.file import FileConnector
    from proxystore.store import Store

    with tempfile.TemporaryDirectory() as tmp_dir:
        with Store('default', FileConnector(tmp_dir), register=True) as store:
            client = Client(..., ps_store=store, ps_threshold=100)  # (2)!

            x = list(range(100))
            p = store.proxy(x)
            y = client.submit(sum, p)

            print(f'Result: {y.result()}')

            client.close()
    ```

    1. Change the import of `Client` from `dask.distributed` to
       `proxystore.ex.plugins.distributed`.
    2. Pass your [`Store`][proxystore.store.base.Store] and threshold object
       size. Serialized objects larger than the threshold size in bytes will
       be serialized using the store you provide and pass-by-proxy.

    The custom [`Client`][proxystore_ex.plugins.distributed.Client] behaves
    exactly as a normal Dask client when `ps_store` is `None`. But when
    ProxyStore is configured, function args, kwargs, and results from
    passed to or from [`Client.submit()`][distributed.Client.submit] and
    [`Client.map()`][distributed.Client.map] will be scanned and proxied as
    necessary based on their size.

    When invoking a function, you can alter this behavior by passing
    `proxy_args=False` and/or `proxy_result=False` to disable proxying for that
    specific function submission to the scheduler.

    !!! warning

        There are some edge cases to be aware of when using the automatic
        proxying. Please read the documentation for
        [`Client.submit()`][proxystore_ex.plugins.distributed.Client.submit]
        and [`Client.map()`][proxystore_ex.plugins.distributed.Client.map] for
        the most up to date details.

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
            However, proxied keyword arguments shared across all functions
            will not be evict if they were proxied.

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
                key = [
                    f'{key}-{tokenize(func, kwargs, *args)}-proxy'
                    for args in zip(*iterables)
                ]

            iterables = tuple(
                proxy_iterable(
                    iterable,
                    store=self._ps_store,
                    threshold=self._ps_threshold if proxy_args else None,
                    evict=False,
                )
                for iterable in iterables
            )

            kwargs = proxy_mapping(
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

        if (
            not (batch_size and batch_size > 1 and total_length > batch_size)
            and self._ps_store is not None
        ):
            for future, *args in zip(futures, *iterables):
                proxied_args_keys = [
                    get_key(x) for x in args if isinstance(x, Proxy)
                ]
                # TODO: how to delete kwargs?
                callback = partial(
                    _evict_proxies_callback,
                    keys=proxied_args_keys,
                    store=self._ps_store,
                )
                future.add_done_callback(callback)

            if any(isinstance(x, Proxy) for x in kwargs.values()):
                warnings.warn(
                    'A keyword argument to map() was proxied, but proxied '
                    'keyword arguments will not be automatically evicted. '
                    'This can lead to memory leaks.',
                    stacklevel=2,
                )

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
                key = f'{funcname(func)}-{tokenize(func, kwargs, *args)}-proxy'
                pure = False

            args = proxy_iterable(
                args,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_args else None,
                # Don't evict data after proxy resolve because we will
                # manually evict after the task future completes.
                evict=False,
            )
            proxied_args_keys.extend(
                get_key(x) for x in args if isinstance(x, Proxy)
            )

            kwargs = proxy_mapping(
                kwargs,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_args else None,
                evict=False,
            )
            proxied_args_keys.extend(
                get_key(x) for x in kwargs.values() if isinstance(x, Proxy)
            )

            # CHANGE WRAPPER TO NOT SERIALIZE STORE
            func = proxy_task_wrapper(
                func,
                store=self._ps_store,
                threshold=self._ps_threshold if proxy_result else None,
                # Pure function results can be cached so we don't want to
                # evict those once the result is consumed
                evict=not pure,
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

        if self._ps_store is not None:
            callback = partial(
                _evict_proxies_callback,
                keys=proxied_args_keys,
                store=self._ps_store,
            )
            future.add_done_callback(callback)

        return future


def _evict_proxies_callback(
    _future: DaskDistributedFuture,
    keys: Iterable[ConnectorKeyT],
    store: Store[Any],
) -> None:
    for key in keys:
        store.evict(key)


def proxy_by_size(
    x: T,
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> T | Proxy[T]:
    """Serialize an object and proxy it if the object is larger enough.

    Args:
        x: Object to possibly proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, the object will not
            be proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        The input object `x` if `x` is smaller than `threshold` otherwise \
        a [`Proxy`][proxystore.proxy.Proxy] of `x`.
    """
    if threshold is None or isinstance(x, Proxy):
        return x

    s = serialize(x)

    if len(s) >= threshold:
        proxy = store.proxy(
            s,
            evict=evict,
            # We can't use populate_target here because we are passing
            # the serialized object to store.proxy(), not the actual object.
            # populate_target=True,
            serializer=lambda x: x,
            skip_nonproxiable=True,
        )

        # This is dangerous code, but is taken from the Proxy constructor
        # to essentially mimic what populate_target=True would have done
        # above but using the actual target object x and not the serialized s.
        object.__setattr__(proxy, '__proxy_target__', x)
        object.__setattr__(proxy, '__proxy_default_class__', x.__class__)
        default_hash: Exception | int
        try:
            default_hash = hash(x)
        except TypeError as e:
            default_hash = e
        object.__setattr__(proxy, '__proxy_default_hash__', default_hash)

        return cast(Proxy[T], proxy)
    else:
        # In this case, we paid the cost of serializing x but did not use
        # that serialization of x so it will be serialized again using
        # Dask's mechanisms. This adds some overhead, but the hope is that
        # the threshold is reasonably set such that it is only small objects
        # which get serialized twice. Large objects above the threshold only
        # get serialized once by ProxyStore and the lightweight proxy is
        # serialized by Dask.
        return x


def proxy_iterable(
    iterable: Iterable[Any],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> tuple:  # type: ignore[type-arg]
    """Proxy values in an iterable larger than the threshold size.

    Args:
        iterable: Iterable containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, no objects will b
            proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Tuple containing the objects yielded by the iterable with objects \
        larger than the threshold size replaced with proxies.
    """
    return tuple(
        proxy_by_size(
            value,
            store=store,
            threshold=threshold,
            evict=evict,
        )
        for value in iterable
    )


def proxy_mapping(
    mapping: Mapping[T, Any],
    store: Store[ConnectorT],
    threshold: int | None = None,
    evict: bool = True,
) -> dict[T, Any]:
    """Proxy values in a mapping larger than the threshold size.

    Args:
        mapping: Mapping containing possibly large values to proxy.
        store: Store to use to proxy objects.
        threshold: Threshold size in bytes. If `None`, no objects will b
            proxied.
        evict: Evict flag value to pass to created proxies.

    Returns:
        Mapping containing the same keys and values as the input mapping \
        but objects larger than the threshold size are replaced with proxies.
    """
    return {
        key: proxy_by_size(
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
) -> Callable[P, T | Proxy[T]]:
    """Proxy task wrapper.

    Wraps a task function to proxy returns values larger than a threshold.

    Args:
        func: Function to wrap.
        store: Store to use to proxy the result.
        threshold: Threshold size in bytes.
        evict: Evict flag value to pass to the created proxy.

    Returns:
        Callable with the same shape as `func` but that returns either the \
        original return type or a factory of the return type which can be \
        used to construct a proxy.
    """
    store_config = store.config()

    @functools.wraps(func)
    def _proxy_wrapper(*args: P.args, **kwargs: P.kwargs) -> T | Proxy[T]:
        result = func(*args, **kwargs)
        # A Store is not serializable so we do not want this closure
        # to capture the store variable. Rather, we capture the config
        # and retrieve the store based on the config.
        func_local_store = get_or_create_store(store_config)
        proxy_or_result = proxy_by_size(
            result,
            store=func_local_store,
            threshold=threshold,
            evict=evict,
        )
        return proxy_or_result

    return _proxy_wrapper
