# Dask with ProxyStore

*Last updated 14 December 2023*

This guide discusses using ProxyStore with
[Dask.distributed](https://distributed.dask.org/en/stable/){target=_blank}.
Using ProxyStore to pass intermediate values between function invocations
can yield considerable speedups in distributed applications.

!!! note

    This guide assumes familiarity with Dask.distributed and ProxyStore.

## Getting Started

Dask.distributed is a library for futures-based distributed computing.
To pass proxy objects created with ProxyStore to
Dask.distributed's [`Client.submit()`][distributed.Client.submit] or
[`Client.map()`][distributed.Client.map] functions, we need to adjust
how we schedule our functions.

Consider this trivial example where we submit [`sum()`][sum] on a list
of numbers to the Dask.distributed scheduler, but we pass the input list as
a proxy.

```python linenums="1" title="example.py"
import tempfile

from dask.distributed import Client
from proxystore.connectors.file import FileConnector
from proxystore.store import Store

with tempfile.TemporaryDirectory() as tmp_dir:
    with Store('default', FileConnector(tmp_dir)) as store:
        client = Client(processes=False)

        x = list(range(100))
        p = store.proxy(x)
        y = client.submit(sum, p)

        print(f'Result: {y.result()}')

        client.close()
```

Running this code will yield this error.

```
$ python example.py
Traceback (most recent call last):
  File "/home/jgpaul/workspace/proxystore-extensions/example.py", line 15, in <module>
    y = client.submit(sum, p)
        ^^^^^^^^^^^^^^^^^^^^^
  File "/home/jgpaul/workspace/proxystore-extensions/venv/lib/python3.11/site-packages/distributed/client.py", line 1943, in submit
    key = funcname(func) + "-" + tokenize(func, kwargs, *args)
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jgpaul/workspace/proxystore-extensions/venv/lib/python3.11/site-packages/dask/base.py", line 964, in tokenize
    hasher = _md5(str(tuple(map(normalize_token, args))).encode())
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jgpaul/workspace/proxystore-extensions/venv/lib/python3.11/site-packages/dask/utils.py", line 641, in __call__
    meth = self.dispatch(type(arg))
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jgpaul/workspace/proxystore-extensions/venv/lib/python3.11/site-packages/dask/utils.py", line 626, in dispatch
    toplevel, _, _ = cls2.__module__.partition(".")
                     ^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'property' object has no attribute 'partition'
```

This is a particularly confusing error at first glance. By default,
Dask.distributed [assumes pure function by default](https://distributed.dask.org/en/latest/client.html#pure-functions){target=_blank}.
This assumption means that results of pure functions can be cached and returned
if the same function is invoked with the same inputs. The function invocations
are tracked using a hash of the function, positional args, and keyword args.
Dask has a mechanism for normalizing arbitrary types to string tokens which
can be used to construct this hash. However, Dask's dispatch mechanism for
the token normalization inspects the `__module__` attribute of the object's
type. This is a problem with [`Proxy`][proxystore.proxy.Proxy] because that
implements `__module__` as a property which gets the `__module__` from the
proxy's target object. Thus, accessing `__module__` is only valid on a
[`Proxy`][proxystore.proxy.Proxy] instance and not the type itself.

There's a lot of moving parts and nuance to why this bug appears, but
the good news is that this error can be avoided by either passing a custom
`key` or `pure=False` to [`Client.submit()`][distributed.Client.submit].
The bad news is that we lose ability to avoid redundant computations
(unless you are careful about reusing the same key).


## Better ProxyStore Integration

Creating proxies to transfer function inputs or results as you see fit
may be sufficient, but a custom
[`Client`][proxystore_ex.plugins.distributed.Client] if provided which will
automate the process of proxying large function inputs or results.


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
    with Store('default', FileConnector(tmp_dir)) as store:
        client = Client(..., ps_store=store, ps_threshold=100)  # (2)!

        x = list(range(100))
        p = store.proxy(x)
        y = client.submit(sum, p)

        print(f'Result: {y.result()}')

        client.close()
```

1. Change the import of `Client` from `dask.distributed` to
   `proxystore.ex.plugins.distributed`.
2. Pass your [`Store`][proxystore.store.base.Store] and threshold object size.
   Serialized objects larger than the threshold size in bytes will be serialized
   using the store you provide and pass-by-proxy.

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
    [`Client.submit()`][proxystore_ex.plugins.distributed.Client.submit] and
    [`Client.map()`][proxystore_ex.plugins.distributed.Client.map] for
    the most up to date details.
