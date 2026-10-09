"""Katana Air Desktop — GPL-3.0-or-later. Local Windows application."""
import asyncio, json, secrets, sys, threading, webbrowser, re, traceback, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from protocol import Amp, paired_amps

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
META=json.loads((ROOT/'metadata.json').read_text(encoding='utf-8'))
TOKEN=secrets.token_urlsafe(32)
loop=asyncio.new_event_loop(); amp=None; ready=threading.Event(); reconnect_target=''

async def recover():
    while True:
        await asyncio.sleep(2)
        if reconnect_target and amp.status=='Disconnected':
            try: await amp.connect(reconnect_target)
            except Exception as exc: amp.error='Reconnecting to the amp: '+str(exc)

async def connect_requested(address):
    global reconnect_target
    reconnect_target=address
    try: await amp.connect(address)
    except Exception:
        reconnect_target=''; raise

async def disconnect_requested():
    global reconnect_target
    reconnect_target=''; await amp.disconnect()
def worker():
    global amp
    asyncio.set_event_loop(loop); amp=Amp(); loop.create_task(recover()); ready.set(); loop.run_forever()
threading.Thread(target=worker,daemon=True).start()
ready.wait()
def run(coroutine):
    future=asyncio.run_coroutine_threadsafe(coroutine,loop)
    try: return future.result(timeout=40)
    except TimeoutError:
        future.cancel(); raise RuntimeError('The operation timed out. Reconnect and refresh the tone.')
async def snapshot():
    return {'status':amp.status,'error':amp.error,'address':amp.address,'values':amp.values(META['parameters']),'blocks':amp.blocks,'badChecksums':amp.bad_checksums,'lastVerified':amp.last_verified,'syncAge':None if amp.last_sync is None else time.monotonic()-amp.last_sync}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def respond(self,status,body,content_type='application/json'):
        data=body if isinstance(body,bytes) else json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type',content_type)
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def valid_host(self): return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.valid_host(): self.respond(403,{'error':'Invalid host'}); return
        path=urlparse(self.path).path
        if path=='/':
            self.respond(200,(ROOT/'index.html').read_bytes().replace(b'__TOKEN__',TOKEN.encode()),'text/html; charset=utf-8')
        elif path=='/api/state': self.respond(200,run(snapshot()))
        elif path=='/api/metadata': self.respond(200,META)
        else: self.respond(404,{'error':'Not found'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-App-Token')!=TOKEN:
            self.respond(403,{'error':'Invalid request'}); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<=length<=2048: raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length) or b'{}'); path=urlparse(self.path).path
            if path=='/api/devices':
                # Reuse the active connection rather than opening/closing a
                # second Windows Bluetooth device object when a page reloads.
                result=[{'name':'KATANA-AIR MIDI','address':amp.address}] if amp.address and amp.status in ('Connected','Connecting') else run(paired_amps())
            elif path=='/api/connect':
                address=data['address'].upper()
                if not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',address): raise ValueError('Choose a Katana-Air device.')
                run(connect_requested(address)); result=run(snapshot())
            elif path=='/api/disconnect': run(disconnect_requested()); result=run(snapshot())
            elif path=='/api/refresh': run(amp.refresh()); result=run(snapshot())
            elif path=='/api/set':
                key=data['id']; p=META['parameters'].get(key)
                allowed={k for b in META['blocks'] for k in b['controls']}
                if key not in allowed: raise ValueError('Unknown tone control')
                value=data['value']
                if isinstance(value,bool) or not isinstance(value,int): raise ValueError('Invalid parameter value')
                run(amp.set_parameter(p,value)); result=run(snapshot())
            elif path=='/api/quit':
                run(disconnect_requested()); result={'ok':True}
                threading.Thread(target=self.server.shutdown,daemon=True).start()
            else: self.respond(404,{'error':'Not found'}); return
            self.respond(200,result)
        except Exception as exc: self.respond(400,{'error':str(exc) or type(exc).__name__})

def main():
    port=int(sys.argv[sys.argv.index('--port')+1]) if '--port' in sys.argv else 0
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    url=f'http://127.0.0.1:{server.server_port}/'
    # Optional local diagnostics, useful without exposing a write credential.
    if '--url-file' in sys.argv:
        Path(sys.argv[sys.argv.index('--url-file')+1]).write_text(url)
    if '--no-browser' not in sys.argv: webbrowser.open(url)
    try: server.serve_forever()
    finally:
        try: run(disconnect_requested())
        finally: server.server_close(); loop.call_soon_threadsafe(loop.stop)
if __name__=='__main__': main()
