"""Enable screen-only Apple VNC for this ephemeral project-test runner."""
import os
import pwd
import socket
import subprocess
import time

password = os.environ.pop('MACOS_VNC_PASSWORD', '')
if not password:
    print('VNC disabled: configure the MACOS_VNC_PASSWORD Actions secret (6-8 printable ASCII characters).')
    raise SystemExit(0)
if not 6 <= len(password) <= 8 or any(ord(c) < 33 or ord(c) > 126 for c in password):
    raise SystemExit('MACOS_VNC_PASSWORD must contain 6-8 printable ASCII characters; legacy VNC truncates longer passwords.')
kickstart = '/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart'
env = dict(os.environ, CO_VNCPW=password)
# Apple's helper accepts the password through CO_VNCPW, keeping it out of argv/logs.
users = ['runner']
try:
    pwd.getpwnam('desktop')
except KeyError:
    pass
else:
    users.append('desktop')
    subprocess.run(['/usr/sbin/dseditgroup', '-o', 'edit', '-a', 'desktop', '-t', 'user', 'com.apple.access_screensharing'], check=True, timeout=45)
command = [kickstart, '-activate', '-configure', '-access', '-on', '-allowAccessFor', '-specifiedUsers', '-users', ','.join(users), '-privs', '-ControlObserve', '-clientopts', '-setvnclegacy', '-vnclegacy', 'yes', '-setvncpw', '-restart', '-agent']
result = subprocess.run(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45)
if result.returncode:
    raise SystemExit('Apple VNC setup failed; no password or helper output is logged.')
subprocess.run(['/bin/launchctl','enable','system/com.apple.screensharing'],check=True)
subprocess.run(['/bin/launchctl','load','-w','/System/Library/LaunchDaemons/com.apple.screensharing.plist'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for _ in range(20):
    try:
        with socket.create_connection(('127.0.0.1',5900),timeout=2) as s:
            s.settimeout(2)
            if s.recv(12).startswith(b'RFB '):
                print('Apple VNC protocol is listening. Viewing and input still require destination validation.')
                raise SystemExit(0)
    except OSError:
        pass
    time.sleep(1)
raise SystemExit('Apple VNC did not become available. Check Screen Sharing in macOS settings.')
