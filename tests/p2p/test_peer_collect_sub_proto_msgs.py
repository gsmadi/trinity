import asyncio
import logging

import pytest

from p2p.tools.paragon import BroadcastData, GetSum
from p2p.tools.factories import ParagonPeerPairFactory


logger = logging.getLogger('testing.p2p.PeerSubscriber')


@pytest.mark.asyncio
async def test_peer_subscriber_filters_messages(request, event_loop):
    async with ParagonPeerPairFactory() as (peer, remote):
        with peer.collect_sub_proto_messages() as collector:
            assert collector in peer._subscribers
            remote.sub_proto.send_broadcast_data(b'broadcast-a')
            remote.sub_proto.send_broadcast_data(b'broadcast-b')
            remote.sub_proto.send_get_sum(7, 8)
            remote.sub_proto.send_broadcast_data(b'broadcast-c')
            # yield to let remote and peer transmit messages.  This can take a
            # small amount of time so we give it a few rounds of the event loop to
            # finish transmitting.
            for _ in range(10):
                await asyncio.sleep(0.01)
                if collector.msg_queue.qsize() >= 4:
                    break

        assert collector not in peer._subscribers

        all_messages = collector.get_messages()
        assert len(all_messages) == 4

        assert isinstance(all_messages[0][1], BroadcastData)
        assert isinstance(all_messages[1][1], BroadcastData)
        assert isinstance(all_messages[2][1], GetSum)
        assert isinstance(all_messages[3][1], BroadcastData)

        # make sure it isn't still collecting
        remote.sub_proto.send_broadcast_data(b'broadcast-d')

        await asyncio.sleep(0.01)

        assert len(collector.get_messages()) == 0
