We always recommend installing packages inside of your virtual environment of choice.
E.g.,
```bash
$ python -m venv venv
$ . venv/bin/activate
```

Once your virtual environment is activated, ProxyStore Extensions with `pip`.

note::
    ProxyStore Extensions will install ProxyStore as a dependency. However,
    none of the extra options will be included with ProxyStore. See the
    [ProxyStore Installation](https://docs.proxystore.dev/main/installation)
    guide for how to install the base ProxyStore package with extra options.

```bash
$ pip install proxystore-ex
```

## Distributed In-Memory Connectors

The [`MargoConnector`][proxystore_ex.connectors.dim.margo.MargoConnector] and
[`UCXConnector`][proxystore_ex.connectors.dim.ucx.UCXConnector] have additional
manual installation steps to be completed before they can be used.

* **Margo:**
    * Install [Mochi-Margo](https://github.com/mochi-hpc/mochi-margo){target=_blank} and the dependencies
    * Install [Py-Mochi-Margo](https://github.com/mochi-hpc/py-mochi-margo){target=_blank}
* **UCX:**
    * Install [UCX](https://github.com/openucx/ucx){target=_blank}
    * Install [UCX-Py](https://github.com/rapidsai/ucx-py){target=_blank}
