"""MofKa publisher and subscriber shims.

Shims to the
[`mofka`](https://github.com/mochi-hpc/mofka){target=_blank}
package.
"""

from __future__ import annotations

import cloudpickle
import json
import sys

if sys.version_info >= (3, 11):  # pragma: >=3.11 cover
    from typing import Self
else:  # pragma: <3.11 cover
    from typing_extensions import Self

from proxystore.stream.events import dict_to_event
from proxystore.stream.events import event_to_dict
from proxystore.stream.events import EndOfStreamEvent
from proxystore.stream.events import EventBatch
from proxystore.stream.events import NewObjectEvent
from proxystore.stream.events import NewObjectKeyEvent

try:
    import pymargo.core
    from mochi.mofka.client import DataDescriptor
    from mochi.mofka.client import MofkaDriver
    from mochi.mofka.client import AdaptiveBatchSize
    from mochi.mofka.client import Ordering

    mofka_import_error = None

except ImportError as e:  # pragma: no cover
    mofka_import_error = e


class MofkaPublisher:
    """Mofka publisher shim.

    Args:
        protocol: Network protocol for communication (e.g., `tcp`, `na+sm`).
        group_file: Bedrock generated group file.
    """

    # TODO: strip code of all of these and leave it to users to specify themselves
    # and just provide the driver.
    def __init__(self, group_file: str) -> None:
        if mofka_import_error is not None:  # pragma: no cover
            raise mofka_import_error

        self._driver = MofkaDriver(group_file)

    def close(self) -> None:
        """Close this publisher."""
        del self.producer
        del self._topic
        del self._driver

    def send_events(self, events: EventBatch) -> None:
        """Publish a message to the stream.

        Args:
            topic: Stream topic to publish message to.
            message: Message as bytes to publish to the stream.
        """

        topic = events.topic
        batch_size = AdaptiveBatchSize
        ordering = Ordering.Strict

        self._topic = self._driver.open_topic(topic)
        self.producer = self._topic.producer(
            batch_size=batch_size,
            ordering=ordering,
        )

        for e in events.events:
            if isinstance(e, NewObjectEvent):
                self.producer.push(
                    metadata=json.dumps(e.metadata),
                    data=cloudpickle.dumps(e.obj),
                )
            else:
                self.producer.push(
                    metadata=json.dumps(event_to_dict(e)),
                    data=cloudpickle.dumps(""),
                )

            # TODO: figure out how to properly batch in mofka
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
        group_file: str,
        topic_name: str,
        subscriber_name: str,
    ) -> None:
        if mofka_import_error is not None:  # pragma: no cover
            raise mofka_import_error

        self._driver = MofkaDriver(group_file)
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
        return self.next_events()

    def next_events(self) -> EventBatch:
        metadata: EndOfStreamEvent | NewObjectKeyEvent | NewObjectEvent

        events = self.consumer.pull().wait()
        data = cloudpickle.loads(events.data[0])

        try:
            metadata = dict_to_event(json.loads(events.metadata))
        except Exception:
            metadata = NewObjectEvent(
                topic=self._topic, metadata=events.metadata, obj=data
            )

        return EventBatch(topic=self._topic, events=[metadata])

    def close(self) -> None:
        """Close this subscriber."""
        del self.consumer
        del self._topic
        del self._driver