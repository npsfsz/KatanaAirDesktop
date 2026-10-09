"""Offline framing checks; no Bluetooth connection or amp writes."""
import unittest,asyncio
from protocol import Amp,MidiDecoder,address_bytes,address_number,message
class ProtocolTests(unittest.TestCase):
    def test_base128_addresses(self):
        for n in (0,127,128,16383,201326592):
            self.assertEqual(address_number(address_bytes(n)),n)
    def test_checksum(self):
        self.assertEqual(sum(message(0x12,[0x60,0,0,0x52],[49])[8:-1])%128,0)
    def test_all_timestamps_and_packet_boundaries(self):
        data=message(0x12,[0x60,0,0,0x52],[49])
        for timestamp in range(128,256):
            payload=bytes([timestamp])+data[:-1]+bytes([timestamp,0xf7])
            for split in range(1,len(payload)):
                decoder=MidiDecoder()
                actual=decoder.feed(b'\x80'+payload[:split])+decoder.feed(b'\x80'+payload[split:])
                self.assertEqual(actual,[data],(timestamp,split))
class LiveSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_releases_remote_notifications_first(self):
        calls=[]
        class Client:
            is_connected=True
            async def stop_notify(self,characteristic): calls.append('unsubscribe')
            async def disconnect(self): calls.append('disconnect')
        amp=Amp();amp.client=Client();await amp.disconnect()
        self.assertEqual(calls,['unsubscribe','disconnect'])
        self.assertEqual(amp.status,'Disconnected')
    async def test_snapshot_does_not_show_partial_reads(self):
        amp=Amp();p={'gain':{'address':[96,0,0,82],'bytes':1}}
        key=address_number(p['gain']['address']);amp.memory[key]=50; amp.publish()
        del amp.memory[key]
        self.assertEqual(amp.values(p),{'gain':50})
        amp.memory[key]=49
        self.assertEqual(amp.values(p),{'gain':50})
        amp.publish();self.assertEqual(amp.values(p),{'gain':49})
    async def test_full_poll_waits_for_every_observed_block(self):
        amp=Amp();amp.tone_block_addresses={address_number(a) for a in ([96,0,0,0],[96,0,1,0],[96,0,18,0])}
        async def partial_send(_):
            for addr in ([96,0,0,0],[96,0,18,0]):
                data=message(0x12,addr,[0]*128)
                amp.receive(None,b'\x80\x80'+data[:-1]+b'\x80\xf7')
        amp.send=partial_send
        with self.assertRaises(RuntimeError): await amp._poll_tone(timeout=.01)
        self.assertEqual(amp.pending_tone_blocks,{address_number([96,0,1,0])})
    async def test_live_reads_wait_for_edit_lock_and_cancel_cleanly(self):
        amp=Amp();amp.status='Connected';called=asyncio.Event()
        async def read(*args,**kwargs): called.set();return bytes(96)
        amp.read=read
        await amp.lock.acquire();task=asyncio.create_task(amp._monitor())
        try:
            await asyncio.sleep(.2);self.assertFalse(called.is_set())
            amp.lock.release();await asyncio.wait_for(called.wait(),1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNotNone(amp.last_sync)
if __name__=='__main__': unittest.main()
