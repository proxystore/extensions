"""Kafka publisher and subscriber shims.

Shims to the
[`confluent-kafka`](https://github.com/confluentinc/confluent-kafka-python){target=_blank}
package.
"""

from __future__ import annotations

import json
import sys

if sys.version_info >= (3, 11):  # pragma: >=3.11 cover
    from typing import Self
else:  # pragma: <3.11 cover
    from typing_extensions import Self

from diaspora_event_sdk import KafkaConsumer
from diaspora_event_sdk import KafkaProducer


class OctopusPublisher:
    """Octopus publisher shim.

    Args:
        client: Octopus producer client.
    """

    def __init__(self, client: KafkaProducer) -> None:
        self.producer = KafkaProducer()

    def close(self) -> None:
        """Close this publisher."""
        self.producer.flush()

    def send(self, topic: str, message: bytes) -> None:
        """Publish a message to the stream.

        Args:
            topic: Stream topic to publish message to.
            message: Message as bytes to publish to the stream.
        """
        print(f"{message.decode('utf-8')}")
        self.producer.send(topic, message.decode('utf-8'))
        self.producer.flush()


class OctopusSubscriber:
    """Kafka subscriber shim.

    This shim is an iterable object which will yield [`bytes`][bytes]
    messages from the stream, blocking on the next message, until the stream
    is closed.

    Args:
        client: Kafka consumer client. The `client` must already be subscribed
            to the relevant topics.
    """

    def __init__(self, client: KafkaConsumer) -> None:
        self.client = client

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> bytes:
        message = self.client.poll(timeout_ms=100)
        print(f'{message=}')
        message = self.client.poll()
        print(f'{message=}')
        return bytes(json.dumps(message), 'utf-8')

    def close(self) -> None:
        """Close this subscriber."""
        self.client.close()
