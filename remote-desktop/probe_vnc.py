"""Verify classic VNC authentication and framebuffer negotiation, without logging secrets."""
import os
import socket
import struct
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES

password = os.environ.pop('MACOS_VNC_PASSWORD', '').encode('ascii')
if not password:
    raise SystemExit('VNC password not configured')
with socket.create_connection(('127.0.0.1',5900),timeout=5) as s:
    s.settimeout(5)
    def read(n):
        data = b''
        while len(data) < n:
            part = s.recv(n-len(data))
            if not part: raise RuntimeError('VNC closed during negotiation')
            data += part
        return data
    assert read(12).startswith(b'RFB '), 'VNC protocol unavailable'
    s.sendall(b'RFB 003.008\n')
    count = read(1)[0]
    assert count and 2 in read(count), 'Classic VNC password authentication unavailable'
    s.sendall(b'\x02')
    challenge = read(16)
    key = bytes(int(format(b,'08b')[::-1],2) for b in password.ljust(8,b'\x00')[:8])
    encrypt = Cipher(TripleDES(key*3),modes.ECB()).encryptor()
    s.sendall(encrypt.update(challenge)+encrypt.finalize())
    assert struct.unpack('!I',read(4))[0] == 0, 'VNC password authentication failed'
    s.sendall(b'\x01')
    init = read(24)
    width,height = struct.unpack('!HH',init[:4])
    assert width > 0 and height > 0, 'VNC framebuffer unavailable'
    name_length = struct.unpack('!I',init[20:24])[0]
    assert name_length < 65536, 'Unexpected VNC server name length'
    read(name_length)
    print(f'VNC password authentication and framebuffer negotiation verified ({width}x{height}). Visible desktop and input still require browser validation.')
