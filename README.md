# ProxyStore Extensions

![PyPI - Version](https://img.shields.io/pypi/v/proxystore-ex)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/proxystore-ex)
![GitHub License](https://img.shields.io/github/license/proxystore/extensions)

[![docs](https://github.com/proxystore/extensions/actions/workflows/docs.yml/badge.svg)](https://github.com/proxystore/extensions/actions)
[![tests](https://github.com/proxystore/extensions/actions/workflows/tests.yml/badge.svg)](https://github.com/proxystore/extensions/actions)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/proxystore/extensions/main.svg)](https://results.pre-commit.ci/latest/github/proxystore/extensions/main)

Extensions for the [ProxyStore](https://github.com/proxystore/proxystore/) package.

This extensions package contains experimental features, features with
non-Python dependencies, and plugins for third-party tools.

## Installation

The extensions package can be installed alongside
[ProxyStore](https://github.com/proxystore/proxystore/).
```bash
$ pip install proxystore[extensions]
```

Alternatively, the package can be installed directly.
```bash
$ pip install proxystore-ex
```

See the [Installation](https://extensions.proxystore.dev/main/installation)
guide for more information about features which require extra dependencies.
See the [Contributing](https://extensions.proxystore.dev/main/contributing)
guide to get started with local development.

## Documentation

ProxyStore's documentation is available at [docs.proxystore.dev](https://docs.proxystore.dev) and supplemental documentation for the extensions package is available at [extensions.proxystore.dev](https://extensions.proxystore.dev).

## Usage

Features in the `proxystore_ex` package can be imported from within
`proxystore` via the [`proxystore.ex`](https://docs.proxystore.dev/latest/api/ex/)
module. This is the recommended method for import extension features. E.g.,

```python
from proxystore_ex.connectors.daos import DAOSConnector  # Direct
from proxystore.ex.connectors.daos import DAOSConnector  # Recommended
```

## Citation

The preferred citations for this code are provided at https://docs.proxystore.dev/latest/publications/.
