"""MofKa publisher and subscriber shims.

Shims to the
[`mofka`](https://github.com/mochi-hpc/mofka){target=_blank}
package.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):  # pragma: >=3.11 cover
    from typing import Self
else:  # pragma: <3.11 cover
    from typing_extensions import Self


import pymargo.core
from mochi.mofka.client import DataDescriptor
from mochi.mofka.client import MofkaDriver
from pymargo.core import Engine


class MofkaPublisher:
    """Mofka publisher shim.

    Args:
        protocol: Network protocol for communication (e.g., `tcp`, `na+sm`).
        group_file: Bedrock generated group file.
    """

    def __init__(self, protocol: str, group_file: str) -> None:
        self._engine = Engine(protocol, pymargo.core.server)
        self._driver = MofkaDriver(group_file, self._engine)

    def close(self) -> None:
        """Close this publisher."""
        del self.producer
        del self._topic
        del self._driver
        self._engine.finalize()
        del self._engine

    def send(self, topic: str, message: bytes) -> None:
        """Publish a message to the stream.

        Args:
            topic: Stream topic to publish message to.
            message: Message as bytes to publish to the stream.
        """
        self._topic = self._driver.open_topic(topic)
        self.producer = self._topic.producer()
        self.producer.push(metadata=message, data=message)
        self.producer.flush()


class MofkaSubscriber:
    """Mofka subscriber shim.

    This shim is an iterable object which will yield [`bytes`][bytes]
    messages from the stream, blocking on the next message, until the stream
    is closed.

    Args:
        protocol: Network protocol for communication (e.g., `tcp`, `na+sm`).
        group_file: Bedrock generated group file.
        topic_name: Name of the topic to subscribe to.
        subscriber_name: Identifier for this current subscriber.
    """

    def __init__(
        self,
        protocol: str,
        group_file: str,
        topic_name: str,
        subscriber_name: str,
    ) -> None:
        self._engine = Engine(protocol, pymargo.core.server)
        self._driver = MofkaDriver(group_file, self._engine)
        self._topic = self._driver.open_topic(topic_name)
        self.consumer = self._topic.consumer(
            name=subscriber_name,
            data_selector=self.data_selector,
            data_broker=self.data_broker,
        )

    @staticmethod
    def data_selector(
        metadata: dict[str, int | float | str],
        descriptor: DataDescriptor,
    ) -> DataDescriptor:
        """Mofka data selector implementation.

        This data selector returns all events.

        Args:
            metadata: Event metadata.
            descriptor: Pointer to the data belonging to the event.

        Returns:
            DataDescriptor: Pointer to event data.
        """
        return descriptor

    @staticmethod
    def data_broker(
        metadata: dict[str, int | float | str],
        descriptor: DataDescriptor,
    ) -> list[bytearray]:
        """Mofka data broker implementation.

        Creates a memory buffer for which consumed event will be placed.

        Args:
            metadata: Event metadata.
            descriptor (DataDescriptor): Pointer to data.

        Returns:
            list[bytearray]: Memory buffer of event size.
        """
        return [bytearray(descriptor.size)]

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> bytes:
        message = self.consumer.pull().wait()
        return bytes(message.data[0])

    def close(self) -> None:
        """Close this subscriber."""
        del self.consumer
        del self._topic
        del self._driver
        self._engine.finalize()
        del self._engine
