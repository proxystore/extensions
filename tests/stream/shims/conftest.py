from __future__ import annotations

import os
import subprocess

import pytest


@pytest.fixture(scope='module')
def _conf_mofka():
    protocol = 'tcp'
    bedrock_conf = 'testing/configuration/mofka_config.json'
    groupfile = 'mofka.json'
    topic = 'default'

    # Start Bedrock
    _ = subprocess.Popen(
        ['bedrock', protocol, '-c', bedrock_conf],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Create topic
    cp = subprocess.run(
        ['mofkactl', 'topic', 'create', topic, '--groupfile', groupfile],
        check=False,
    )
    assert cp.returncode == 0

    # Add partition
    cp = subprocess.run(
        [
            'mofkactl',
            'partition',
            'add',
            topic,
            '--type',
            'memory',
            '--rank',
            '0',
            '--groupfile',
            groupfile,
        ],
        check=False,
    )
    assert cp.returncode == 0

    yield

    os.remove(groupfile)
