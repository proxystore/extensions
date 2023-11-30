ProxyStore Extensions should be installed alongside
[ProxyStore](https://github.com/proxystore/proxystore){target=_blank}.
```bash
$ pip install proxystore[extensions]
```
Checkout [ProxyStore's Installation Guide](https://docs.proxystore.dev/latest/installation/){target=_blank} for more details.


!!! note

    ProxyStore Extensions can be installed directly.
    ```bash
    $ pip install proxystore-ex
    ```
    This is generally not recommended because this will install the base
    ProxyStore package if it is not installed already. This means that
    none of the extra options from ProxyStore that you may need will be
    installed. See the
    [ProxyStore Installation Guide](https://docs.proxystore.dev/main/installation)
    for how to install the base ProxyStore package with extra options.

## Distributed In-Memory Connectors

The [`MargoConnector`][proxystore_ex.connectors.dim.margo.MargoConnector] and
[`UCXConnector`][proxystore_ex.connectors.dim.ucx.UCXConnector] have additional
manual installation steps to be completed before they can be used. These
steps are reasonably involved and may change over time so checkout the
following resources for the most up-to-date instructions.

* **Margo:**
    * Install [Mochi-Margo](https://github.com/mochi-hpc/mochi-margo){target=_blank} and the dependencies
    * Install [Py-Mochi-Margo](https://github.com/mochi-hpc/py-mochi-margo){target=_blank}
* **UCX:**
    * Install [UCX](https://github.com/openucx/ucx){target=_blank}
    * Install [UCX-Py](https://github.com/rapidsai/ucx-py){target=_blank}
