from __future__ import annotations


import pytest

from proxystore.stream.events import EventBatch
from proxystore.stream.events import NewObjectEvent
from proxystore.ex.stream.shims.mofka import MofkaPublisher
from proxystore.ex.stream.shims.mofka import MofkaSubscriber


@pytest.mark.usefixtures('_conf_mofka')
def test_basic_publish_subscribe() -> None:
    groupfile = 'mofka.json'
    protocol = 'tcp'
    topic = 'default'
    subscriber_name = 'sub1'

    publisher = MofkaPublisher(protocol=protocol, group_file=groupfile)
    subscriber = MofkaSubscriber(
        protocol=protocol,
        group_file=groupfile,
        topic_name=topic,
        subscriber_name=subscriber_name,
    )

    messages: list[NewObjectEvent] = [
        NewObjectEvent(topic=topic, metadata={'some_data': i}, obj=i)
        for i in range(1, 4)
    ]
    events = EventBatch(topic=topic, events=messages)
    publisher.send_events(events)

    publisher.close()

    for expected, received in zip(messages, subscriber):
        assert received.events[0].obj == expected.obj

    subscriber.close()
