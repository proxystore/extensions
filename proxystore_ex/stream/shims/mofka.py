"""MofKa publisher and subscriber shims.

Shims to the
[`mofka`](https://github.com/mochi-hpc/mofka){target=_blank}
package.
"""

from __future__ import annotations

import cloudpickle
import json
import sys
import logging

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
    from mochi.mofka.client import AdaptiveBatchSize
    from mochi.mofka.client import ByteArrayAllocator
    from mochi.mofka.client import DataDescriptor
    from mochi.mofka.client import FullDataSelector
    from mochi.mofka.client import MofkaDriver
    from mochi.mofka.client import Ordering
    from mochi.mofka.client import ThreadPool

    mofka_import_error = None

except ImportError as e:  # pragma: no cover
    mofka_import_error = e


logger = logging.getLogger(__name__)


class MofkaStreamDriver:
    """Singleton class for the Mofka Driver.

    There can only be one driver per process leading to the need for this singleton.

    Args:
        group_file: Bedrock generated group file.
    """

    _instances = {}

    def __new__(cls, group_file):
        if group_file not in cls._instances:
            cls._instances[group_file] = super(MofkaStreamDriver, cls).__new__(
                cls,
            )
            cls._instances[group_file].driver = MofkaDriver(
                group_file=group_file, use_progress_thread=True
            )
        return cls._instances[group_file]


class MofkaPublisher:
    """Mofka publisher shim.

    Args:
        group_file: Bedrock generated group file.
    """

    # TODO: strip code of all of these and leave it to users to specify themselves
    # and just provide the driver.
    def __init__(self, group_file: str) -> None:
        if mofka_import_error is not None:  # pragma: no cover
            raise mofka_import_error

        logger.info("Mofka driver created in Producer")
        self._driver = MofkaStreamDriver(group_file=group_file).driver
        self._topics: dict = {}
        self._producers: dict = {}

    def close(self) -> None:
        """Close this publisher."""
        logger.info("Closing publisher")
        del self._topics
        del self._producers
        del self._driver

    def send_events(self, events: EventBatch) -> None:
        """Publish a message to the stream.

        Args:
            topic: Stream topic to publish message to.
            message: Message as bytes to publish to the stream.
        """

        logger.info("Pushing events to topic")

        topic = events.topic
        batch_size = AdaptiveBatchSize
        ordering = Ordering.Strict

        if topic not in self._topics.keys():
            open_topic = self._driver.open_topic(topic)

            producer = open_topic.producer(
                batch_size=batch_size,
                ordering=ordering,
            )
            self._topics[topic] = open_topic
            self._producers[topic] = producer

        else:
            producer = self._producers[topic]

        # TODO: figure out how to properly batch in mofka
        producer.flush()

        for e in events.events:
            if isinstance(e, NewObjectEvent):
                producer.push(
                    metadata=e.metadata,
                    data=cloudpickle.dumps(e.obj),
                )
            else:
                producer.push(
                    metadata=event_to_dict(e),
                    data=cloudpickle.dumps(""),
                )

        logger.info("Event push completed")


class MofkaSubscriber:
    """Mofka subscriber shim.

    This shim is an iterable object which will yield [`bytes`][bytes]
    messages from the stream, blocking on the next message, until the stream
    is closed.

    Args:
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

        logger.info("Mofka driver created in subscriber")
        self._driver = MofkaStreamDriver(group_file=group_file).driver
        self._topic = self._driver.open_topic(topic_name)
        self.consumer = self._topic.consumer(
            name=subscriber_name,
            data_selector=FullDataSelector,
            data_broker=ByteArrayAllocator,
            thread_pool=ThreadPool(1),
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

        logger.info(f"Mofka subscriber listening for messages in topic {self._topic}")
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
