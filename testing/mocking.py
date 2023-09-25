from __future__ import annotations

import contextlib
from typing import Generator
from unittest import mock


@contextlib.contextmanager
def mock_multiprocessing() -> Generator[None, None, None]:
    """Mock `Process.{start,join,terminate}`."""
    with mock.patch('multiprocessing.process.BaseProcess.start'), mock.patch(
        'multiprocessing.process.BaseProcess.join',
    ), mock.patch(
        'multiprocessing.process.BaseProcess.terminate',
    ):
        yield
