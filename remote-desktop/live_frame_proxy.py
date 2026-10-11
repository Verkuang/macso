"""Temporary loopback compression proxy; all authentication stays in the original server."""
import hashlib
import http.client
import os
import select
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

UPSTREAM = ('127.0.0.1', 6080)
lock = threading.Lock()
cached = (None, None)
HOP = {'connection', 'transfer-encoding', 'content-length', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'upgrade'}
FIT_SCREEN = b"\nfunction fitScreen(){const img=document.getElementById('screen'),stage=document.getElementById('stage');if(!img.naturalWidth||!img.naturalHeight)return;const scale=Math.min(stage.clientWidth/img.naturalWidth,stage.clientHeight/img.naturalHeight);img.style.width=(img.naturalWidth*scale)+'px';img.style.height=(img.naturalHeight*scale)+'px';} document.getElementById('screen').addEventListener('load',fitScreen);window.addEventListener('resize',fitScreen);\n"

def compress(data):
    global cached
    key = hashlib.sha256(data).digest()
    with lock:
        if cached[0] == key:
            return cached[1]
        with tempfile.TemporaryDirectory(prefix='macso-frame-') as folder:
            path = Path(folder)/'frame.jpg'
            path.write_bytes(data)
            subprocess.run(['/usr/bin/sips', '-Z', '1280', '-s', 'format', 'jpeg', '-s', 'formatOptions', '45', str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            result = path.read_bytes()
        cached = (key, result)
        return result

class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.settimeout(35)
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.forward()
    def do_POST(self):
        self.forward()
    def forward(self):
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            return self.websocket()
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 16384:
                raise ValueError()
            body = self.rfile.read(length) if length else None
        except ValueError:
            self.send_error(400)
            self.close_connection = True
            return
        conn = http.client.HTTPConnection(*UPSTREAM, timeout=30)
        try:
            conn.request(self.command, self.path, body=body, headers={k:v for k,v in self.headers.items() if k.lower() not in HOP})
            response = conn.getresponse()
            data = response.read()
            headers = response.getheaders()
            if response.status == 200 and urlsplit(self.path).path == '/app.js':
                data += FIT_SCREEN
            if response.status == 200 and urlsplit(self.path).path == '/frame.jpg' and data.startswith(b'\xff\xd8'):
                original_size = len(data)
                try:
                    data = compress(data)
                    headers += [('X-Frame-Original-Bytes',str(original_size)), ('X-Frame-Optimized','1280-q45')]
                except (OSError, subprocess.SubprocessError):
                    pass
            self.send_response(response.status)
            for k,v in headers:
                if k.lower() not in HOP:
                    self.send_header(k,v)
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.close_connection = True
        finally:
            conn.close()
    def websocket(self):
        # Relay the original handshake unchanged; upstream enforces cookie and origin.
        self.close_connection = True
        try:
            with socket.create_connection(UPSTREAM, timeout=5) as remote:
                request = f'{self.command} {self.path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k,v in self.headers.items()) + '\r\n'
                remote.sendall(request.encode('latin-1'))
                remote.settimeout(None)
                while True:
                    readable,_,_ = select.select([self.connection,remote],[],[],30)
                    if not readable:
                        continue
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (remote if source is self.connection else self.connection).sendall(data)
        except OSError:
            pass

def main():
    server = ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('DESKTOP_PROXY_PORT','6081'))),Proxy)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    while True:
        threading.Event().wait(10)
        try:
            with socket.create_connection(UPSTREAM,timeout=2):
                pass
        except OSError:
            break
    server.shutdown()
    server.server_close()

if __name__ == '__main__':
    main()
