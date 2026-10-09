"""Katana-Air BLE MIDI transport. GPL-3.0-or-later.

Roland framing and parameter-map research: AIR FxFloorBoard by Colin Willcocks.
Only live tone and explicitly listed tone-related global parameters are exposed.
"""
import asyncio
import time
from bleak import BleakClient, BleakScanner
from bleak.backends.winrt.client import BleakClientWinRT

MIDI = '7772e5db-3868-4112-a1a9-f2669d106bf3'
PREFIX = bytes.fromhex('f0 41 00 00 00 00 50')

def address_number(address):
    value=0
    for b in address: value=value*128+b
    return value

def address_bytes(value):
    return bytes((value >> s)&127 for s in (21,14,7,0))

def message(command,address,data):
    payload=bytes(address)+bytes(data)
    return PREFIX+bytes([command])+payload+bytes([(-sum(payload))&127,0xf7])

class MidiDecoder:
    """Reassemble SysEx across BLE packets, stripping BLE timestamps."""
    def __init__(self): self.buffer=bytearray(); self.after_timestamp=False
    def feed(self,packet):
        result=[]
        for b in packet[1:]:
            if self.after_timestamp:
                self.after_timestamp=False
                if b==0xf0: self.buffer=bytearray([b])
                elif b==0xf7 and self.buffer:
                    self.buffer.append(b); result.append(bytes(self.buffer)); self.buffer.clear()
                elif b<128 and self.buffer: self.buffer.append(b)
            elif b>=128: self.after_timestamp=True
            elif self.buffer: self.buffer.append(b)
        return result

class PairedClient(BleakClientWinRT):
    async def connect(self,*args,**kwargs):
        # Bleak otherwise scans for advertising even for an existing pairing.
        self._device_info=int(self.address.replace(':',''),16)
        return await super().connect(*args,**kwargs)

class Amp:
    def __init__(self):
        self.client=None; self.memory={}; self.view_memory={}; self.changed=asyncio.Event()
        self.monitor=None; self.tone_version=0; self.last_sync=None
        self.tone_block_addresses=set(); self.pending_tone_blocks=set()
        self.decoder=MidiDecoder(); self.blocks=0; self.bad_checksums=0
        self.identity=None; self.lock=asyncio.Lock(); self.status='Disconnected'
        self.address=''; self.firmware_raw=''; self.error=''; self.last_verified=''
    def disconnected(self,*_):
        self.status='Disconnected'; self.memory.clear(); self.view_memory.clear(); self.last_sync=None
    def receive(self,_,packet):
        for data in self.decoder.feed(packet):
            if data[:6]==bytes.fromhex('f0 7e 00 06 02 41'):
                if data[6:8]==b'\x50\x00': self.identity=data
                self.changed.set()
            if data[:8]!=PREFIX+b'\x12' or len(data)<15: continue
            if sum(data[8:-1])%128:
                self.bad_checksums+=1; continue
            start=address_number(data[8:12])
            self.memory.update({start+i:b for i,b in enumerate(data[12:-2])})
            if data[8]==0x60 and len(data[12:-2])>=128:
                self.tone_block_addresses.add(start); self.pending_tone_blocks.discard(start)
            if data[8:12]==bytes([0x60,0,0x12,0]): self.tone_version+=1
            self.blocks+=1; self.changed.set()
    async def send(self,data):
        if not self.client or not self.client.is_connected: raise RuntimeError('Connect to the amp first.')
        stamp=int(time.monotonic()*1000)&8191
        header=0x80|((stamp>>7)&63); low=0x80|(stamp&127)
        packet=bytes([header,low])+data[:-1]+bytes([low,0xf7])
        maximum=self.client.services.get_characteristic(MIDI).max_write_without_response_size
        # Continuations contain a BLE header but no extra timestamp before SysEx data.
        first=True
        while packet:
            count=maximum if first else maximum-1
            part=packet[:count]; packet=packet[count:]
            await self.client.write_gatt_char(MIDI,part if first else bytes([header])+part,response=False)
            first=False
            if packet: await asyncio.sleep(.02)
    async def connect(self,address):
        async with self.lock:
            await self._disconnect()
            self.status='Connecting'; self.error=''; self.address=address
            try:
                self.client=BleakClient(address,backend=PairedClient,timeout=20,disconnected_callback=self.disconnected,winrt={'use_cached_services':False})
                await self.client.connect()
                if not self.client.services.get_characteristic(MIDI):
                    raise RuntimeError('Windows did not expose the MIDI service. Close other editors and reconnect.')
                await self.client.start_notify(MIDI,self.receive)
                self.identity=None; self.decoder=MidiDecoder()
                await self.send(bytes.fromhex('f0 7e 00 06 01 f7'))
                deadline=time.monotonic()+4
                while not self.identity and time.monotonic()<deadline:
                    self.changed.clear()
                    try: await asyncio.wait_for(self.changed.wait(),.5)
                    except asyncio.TimeoutError: pass
                if not self.identity: raise RuntimeError('The amp did not answer the Katana-Air identity request.')
                try: self.firmware_raw=bytes(await self.client.read_gatt_char('00002a26-0000-1000-8000-00805f9b34fb')).decode(errors='replace')
                except Exception: self.firmware_raw=''
                await self._refresh()
                self.status='Connected'
                self.monitor=asyncio.create_task(self._monitor())
            except Exception as exc:
                await self._disconnect(); self.error=str(exc) or type(exc).__name__; raise
    async def _disconnect(self):
        if self.monitor:
            self.monitor.cancel()
            try: await self.monitor
            except asyncio.CancelledError: pass
            self.monitor=None
        client=self.client; self.client=None
        if client: await self._close_client(client)
        self.status='Disconnected'; self.memory.clear(); self.view_memory.clear(); self.last_sync=None
        self.tone_block_addresses.clear(); self.pending_tone_blocks.clear()
    async def _close_client(self,client):
        # WinRT disconnect removes local callbacks but leaves the remote CCCD
        # enabled. Explicitly release notifications before closing the session.
        if client.is_connected:
            try: await asyncio.wait_for(client.stop_notify(MIDI),2)
            except Exception: pass
        try: await client.disconnect()
        except Exception: pass
    async def disconnect(self):
        async with self.lock: await self._disconnect()
    async def read(self,address,size,timeout=4):
        start=address_number(address)
        for i in range(size): self.memory.pop(start+i,None)
        self.changed.clear()
        await self.send(message(0x11,address,address_bytes(size)))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if all(start+i in self.memory for i in range(size)):
                return bytes(self.memory[start+i] for i in range(size))
            self.changed.clear()
            try: await asyncio.wait_for(self.changed.wait(),max(.01,deadline-time.monotonic()))
            except asyncio.TimeoutError: break
        raise RuntimeError('The amp did not return this setting. Reconnect or refresh before editing it.')
    async def _refresh(self):
        self.memory.clear(); self.blocks=0; self.changed.clear()
        await self.send(message(0x11,[0x60,0,0,0],[0,0,0x13,0]))
        final=address_number([0x60,0,0x12,0x1e])
        deadline=time.monotonic()+7
        while final not in self.memory and time.monotonic()<deadline:
            self.changed.clear()
            try: await asyncio.wait_for(self.changed.wait(),.5)
            except asyncio.TimeoutError: pass
        if final not in self.memory: raise RuntimeError('The live tone read was incomplete. Keep the amp nearby and reconnect.')
        # Source map preamp fields at 21..28 are incorrect for this amp.
        # Read the empirically confirmed preamp region directly.
        await self.read([0x60,0,0,0x50],13)
        try: await self.read([0,0,4,0x30],15)
        except RuntimeError: pass
        try: await self.read([0,0,4,0x10],26,timeout=2)
        except RuntimeError: pass
        self.publish()
    async def refresh(self):
        async with self.lock:
            await self._refresh(); self.error=''
    async def _poll_tone(self,timeout=3):
        version=self.tone_version
        self.pending_tone_blocks=set(self.tone_block_addresses)
        await self.send(message(0x11,[0x60,0,0,0],[0,0,0x13,0]))
        deadline=time.monotonic()+timeout
        while self.tone_version==version or self.pending_tone_blocks:
            self.changed.clear()
            remaining=deadline-time.monotonic()
            if remaining<=0: raise RuntimeError('Waiting for the amp. Keep it nearby or reconnect.')
            try: await asyncio.wait_for(self.changed.wait(),remaining)
            except asyncio.TimeoutError: raise RuntimeError('Waiting for the amp. Keep it nearby or reconnect.')
    def publish(self):
        self.view_memory=dict(self.memory); self.last_sync=time.monotonic()
    async def _monitor(self):
        global_due=time.monotonic()+5; tone_due=time.monotonic()+1.5; failures=0
        while self.status=='Connected':
            await asyncio.sleep(.15)
            try:
                # All reads and edits share this lock; no background read can
                # consume an edit's reply or overwrite its verification.
                async with self.lock:
                    if self.status!='Connected': break
                    # Panel preamp/booster controls get frequent, small reads.
                    # Read all effect algorithms less often to limit BLE traffic.
                    await self.read([0x60,0,0,0],0x60,timeout=2)
                    # These are the combined physical knob positions and LEDs,
                    # distinct from individual effect parameters.
                    await self.read([0,0,4,0x10],26,timeout=2)
                    if time.monotonic()>=tone_due:
                        await self._poll_tone()
                        tone_due=time.monotonic()+1.5
                    if time.monotonic()>=global_due:
                        start=address_number([0,0,4,0x30])
                        cached={k:self.memory[k] for k in range(start,start+15) if k in self.memory}
                        try: await self.read([0,0,4,0x30],15,timeout=2)
                        except RuntimeError: self.memory.update(cached)
                        global_due=time.monotonic()+5
                    self.publish(); self.error=''; failures=0
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.error=str(exc)
                failures+=1
                if failures>=3 and self.client:
                    await self._close_client(self.client)
                    self.disconnected()
                await asyncio.sleep(1)
    async def set_parameter(self,parameter,value):
        async with self.lock:
            if self.status!='Connected': raise RuntimeError('Connect to the amp first.')
            if str(value) not in parameter['options']: raise ValueError('Value is outside the parameter range.')
            addr=parameter['address']; size=parameter['bytes']
            original=await self.read(addr,size)
            old_value=0
            for b in original: old_value=old_value*128+b
            if str(old_value) not in parameter['options']:
                raise RuntimeError('The amp returned a value this map does not recognize. No change was sent.')
            expected=bytes([value]) if size==1 else bytes([value//128,value%128])
            if expected!=original:
                await self.send(message(0x12,addr,expected))
                await asyncio.sleep(.07)
                try:
                    actual=await self.read(addr,size)
                    if actual!=expected: raise RuntimeError('The amp returned a different value. This control is not verified for its firmware.')
                except Exception as verification_error:
                    # Best-effort rollback; never hide a failed verification.
                    try:
                        await self.send(message(0x12,addr,original))
                        await asyncio.sleep(.07)
                        if await self.read(addr,size)!=original: raise RuntimeError('Restore readback mismatch')
                    except Exception as restore_error:
                        raise RuntimeError(f'Edit verification failed, and restoration could not be confirmed. Refresh and check this setting. {restore_error}') from verification_error
                    raise verification_error
            self.publish(); self.last_verified=parameter['label']; self.error=''
            return int.from_bytes(expected,'big') if size==1 else expected[0]*128+expected[1]
    def values(self,parameters):
        result={}
        for key,p in parameters.items():
            start=address_number(p['address']); size=p['bytes']
            if all(start+i in self.view_memory for i in range(size)):
                value=0
                for i in range(size): value=value*128+self.view_memory[start+i]
                result[key]=value
        return result

async def paired_amps():
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation
    result=[]
    for d in await DeviceInformation.find_all_async_aqs_filter(BluetoothLEDevice.get_device_selector_from_pairing_state(True)):
        if 'KATANA-AIR' not in d.name.upper(): continue
        device=await BluetoothLEDevice.from_id_async(d.id)
        if device:
            raw=f'{device.bluetooth_address:012X}'
            result.append({'name':d.name,'address':':'.join(raw[i:i+2] for i in range(0,12,2))}); device.close()
    if not result:
        for d in await BleakScanner.discover(timeout=5):
            if d.name and 'KATANA-AIR' in d.name.upper(): result.append({'name':d.name,'address':d.address})
    return result
