from proxystore.stream import StreamProducer
from proxystore.stream import StreamConsumer


class Exchange:
    producer: StreamProducer
    consumer: StreamConsumer

    def __init__(self, producer: StreamProducer, consumer: StreamConsumer):
        self.producer = producer
        self.consumer = consumer

    # probably want to make this async ?
    def forward(self, topic: str) -> None:
        for event in self.consumer:
            self.producer.send(topic=topic, obj=event)

    # this might need to be for a single topic, unless the exchange can forward to many different topics
    def close(self, topics: list[str]) -> None:
        self.producer.close(topics=topics)
        self.consumer.close()
