import base64
import collections
import http.client
import json
import os
import socket
import socketserver
import struct
import threading
import time
import types
import unittest
import server
import vnc_gateway

class Target(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b'RFB 003.008\n')
        while True:
            data=self.request.recv(65536)
            if not data: return
            self.request.sendall(data)

class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target=socketserver.ThreadingTCPServer(('127.0.0.1',0),Target)
        cls.target.daemon_threads=True
        vnc_gateway.VNC_PORT=cls.target.server_address[1]
        cls.http=server.DesktopServer(('127.0.0.1',0),server.Handler)
        cls.http.desktop=types.SimpleNamespace(password=b'test-only',duration=120,started=False,deadline=time.time()+120,session_lock=threading.Lock(),sessions={},attempts=collections.defaultdict(collections.deque),finished=threading.Event())
        for s in [cls.http,cls.target]: threading.Thread(target=s.serve_forever,daemon=True).start()
        cls.host='127.0.0.1:'+str(cls.http.server_address[1])
    @classmethod
    def tearDownClass(cls):
        cls.http.desktop.finished.set()
        for s in [cls.http,cls.target]: s.shutdown();s.server_close()
    def request(self,path,method='GET',body=None,headers=None):
        c=http.client.HTTPConnection(self.host,timeout=3)
        c.request(method,path,body,headers or {})
        r=c.getresponse();out=(r.status,dict(r.getheaders()),r.read());c.close();return out
    def login(self):
        status,headers,_=self.request('/api/login','POST',json.dumps({'password':'test-only'}),{'Content-Type':'application/json'})
        self.assertEqual(status,200)
        return headers['Set-Cookie'].split(';')[0]
    def ws(self,cookie='',origin=None):
        s=socket.create_connection(self.http.server_address,timeout=3)
        key=base64.b64encode(os.urandom(16)).decode()
        headers=f'GET /vnc-socket HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\nOrigin: {origin or "http://"+self.host}\r\nCookie: {cookie}\r\n\r\n'
        s.sendall(headers.encode());response=b''
        while not response.endswith(b'\r\n\r\n'): response+=s.recv(1)
        return s,response
    def frame(self,s):
        def read(n):
            b=b''
            while len(b)<n:
                chunk=s.recv(n-len(b))
                if not chunk: return b
                b+=chunk
            return b
        head=read(2)
        if not head: return None
        n=head[1]&127
        if n==126:n=struct.unpack('!H',read(2))[0]
        if n==127:n=struct.unpack('!Q',read(8))[0]
        return head[0]&15,read(n)
    def send(self,s,data):
        mask=os.urandom(4)
        s.sendall(bytes([0x82,0x80|len(data)])+mask+bytes(b^mask[i%4] for i,b in enumerate(data)))
    def test_protected_http(self):
        for p in ['/vnc.js','/vnc.css','/api/vnc-status','/vnc-static/core/rfb.js']:
            self.assertEqual(self.request(p)[0],401)
        self.assertEqual(self.request('/vnc')[0],302)
        cookie=self.login();h={'Cookie':cookie}
        self.assertEqual(self.request('/vnc',headers=h)[0],200)
        self.assertTrue(json.loads(self.request('/api/vnc-status',headers=h)[2])['available'])
        self.assertEqual(self.request('/vnc-static/core/rfb.js',headers=h)[0],200)
        self.assertEqual(self.request('/vnc-static/%2e%2e/server.py',headers=h)[0],404)
    def test_unauthenticated_and_cross_origin_upgrade(self):
        s,r=self.ws();self.assertIn(b'401',r.split(b'\r\n')[0]);s.close()
        s,r=self.ws(self.login(),'http://unrelated.example');self.assertIn(b'403',r.split(b'\r\n')[0]);s.close()
    def test_bidirectional_rfb_and_logout_revocation(self):
        cookie=self.login();s,r=self.ws(cookie);self.assertIn(b'101',r.split(b'\r\n')[0])
        self.assertEqual(self.frame(s),(2,b'RFB 003.008\n'))
        self.send(s,b'RFB 003.008\n');self.assertEqual(self.frame(s),(2,b'RFB 003.008\n'))
        token=cookie.split('=',1)[1]
        self.assertEqual(self.request('/api/logout','POST','{}',{'Cookie':cookie,'X-Desktop-CSRF':token,'Content-Type':'application/json'})[0],200)
        self.assertEqual(self.request('/vnc.js',headers={'Cookie':cookie})[0],401)
        s.settimeout(3);event=self.frame(s);self.assertTrue(event is None or event[0]==8);s.close()
    def test_unavailable_target(self):
        port=vnc_gateway.VNC_PORT
        probe=socket.socket();probe.bind(('127.0.0.1',0));vnc_gateway.VNC_PORT=probe.getsockname()[1]
        try:
            s,r=self.ws(self.login());self.assertIn(b'503',r.split(b'\r\n')[0]);s.close()
        finally:vnc_gateway.VNC_PORT=port;probe.close()

if __name__=='__main__':unittest.main()
