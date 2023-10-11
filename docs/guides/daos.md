# DAOS at ALCF

*Last updated 10 October 2023*

This guide shows you how to use ProxyStore with DAOS at
[ALCF](https://www.alcf.anl.gov/){target=_blank}.

!!! note

    While some parts of this guide is specific to ALCF, the general steps
    should apply to any system with a DAOS cluster.

The Distributed Asynchronous Object Storage (DAOS) is a distributed object
store designed for high-speed non-volatile memory storage like Intel Optane
and NVMe. ALCF's Sunspot and Aurora systems have or will have DAOS deployments.

ProxyStore Extensions provides support for DAOS via the
[`DAOSConnector`][proxystore_ex.connectors.daos.DAOSConnector] which uses
[PyDAOS](https://www.intel.com/content/www/us/en/developer/articles/case-study/unlock-the-power-of-daos-in-python-with-pydaos.html)
internally to connect to a DAOS pool.

References:

* [DAOS v2.4 Documentation](https://docs.daos.io/v2.4/){target=_blank}
* [PyDAOS Introduction](https://www.intel.com/content/www/us/en/developer/articles/case-study/unlock-the-power-of-daos-in-python-with-pydaos.html){target=_blank}
* [PyDAOS v2.4 Implementation](https://github.com/daos-stack/daos/tree/release/2.4/src/client/pydaos){target=_blank}
* [DAOS on ALCF's Sunspot](https://www.alcf.anl.gov/support-center/aurorasunspot/getting-started-sunspot#daos){target=_blank}

## Installation

PyDAOS is automatically installed into your systems Python and does not
currently provide any wheels for pip installation. This means that on Sunspot,
PyDAOS is only available via the Python 3.6 installation which is older than
what ProxyStore is compatible with. To get around this, we will create a
newer Python virtual environment and copy the system version into the virtual
environment.

```bash
# Load necessary modules on Sunspot
module load daos
module load cray-python

# Create a virtual environment with ProxyStore Extensions installed
python -m venv venv
. venv/bin/activate
pip install proxystore-ex

# Copy the system pydaos into our environment
cp -r /usr/lib64/python3.6/site-packages/pydaos/ $PWD/venv/lib64/python3.9/site-packages/

# Verify that pydaos imports
python -c "import pydaos"
```

## Create a DAOS Pool and Container

PyDAOS requires an existing DAOS pool and container.
On Sunspot, a DAOS pool allocation can be requested from ALCF support.
Once you have a DAOS pool and its name (for ALCF this will be the name of the
allocation you requested it under), you can create a container in the pool.
The type must by `PYTHON` for use with PyDAOS, but the container label
can be anything you want.

```bash
daos container create $POOL_NAME --type=PYTHON --label=demo-container
```

## Create a Connector

Creating a [`DAOSConnector`][proxystore_ex.connectors.daos.DAOSConnector]
is simple.

```python
from proxystore_ex.connectors.daos import DAOSConnector

with DAOSConnector(
    pool=...,
    container='demo-container',
    namespace='proxystore',
) as connector:
    key = connector.put(b'data')
    assert connector.exists(key)
    assert connector.get(key) == b'data'

    connector.evict(key)
    assert not connector.exists(key)
```

The `namespace` argument is used as the name for the DAOS dictionary created
within the DAOS container that you provided. All operations by the connector
will be done within that "namespace" or dictionary. This is helpful for
preventing ProxyStore from clashing with other operations from other programs
on the same container.

## Using with a Store

A [`DAOSConnector`][proxystore_ex.connectors.daos.DAOSConnector] can be used
to initialize a ProxyStore [`Store`][proxystore.store.base.Store].
Learn more about the [`Store`][proxystore.store.base.Store] interface in the
[Get Started](https://docs.proxystore.dev/main/get-started/) guide.

```python
from proxystore.store import Store
from proxystore_ex.connectors.daos import DAOSConnector

connector = DAOSConnector
    pool=...,
    container='demo-container',
    namespace='proxystore',
)

with Store('my-store' connector) as store:
    key = store.put(my_object)
    assert store.get(my_object)

    p = store.proxy(my_object)

    assert isinstance(p, type(my_object))
```
