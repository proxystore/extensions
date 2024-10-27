from __future__ import annotations

import json

import pytest

from proxystore_ex.stream.shims.mofka import MofkaPublisher
from proxystore_ex.stream.shims.mofka import MofkaSubscriber


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

    messages = [
        json.dumps({'data': f'message_{i}'}).encode() for i in range(3)
    ]
    for message in messages:
        publisher.send('default', message)

    publisher.close()

    for expected, received in zip(messages, subscriber):
        assert received == expected

    subscriber.close()
