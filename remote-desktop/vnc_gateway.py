"""Cookie-protected noVNC on the existing private desktop HTTP endpoint."""
import mimetypes
import select
import socket
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit
VNC_PORT = 5900

HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mac 网页 VNC</title><link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/vnc.css"><header><strong>Mac 网页 VNC</strong><a href="/">原网页桌面</a><span class="spacer"></span><label for="vncPassword">VNC 密码</label><input id="vncPassword" type="password" autocomplete="off" maxlength="8"><button id="connect">连接</button><button id="disconnect">断开</button><button id="full">全屏</button></header><div id="info" role="status">正在检查 VNC 服务…</div><div id="view"></div><script type="module" src="/vnc.js"></script></html>'''

CSS = '#view{height:calc(100vh - 130px);background:#05080c}#info{padding:12px;color:#b6c7de}header input{width:160px}'

JS = '''import RFB from '/vnc-static/core/rfb.js';
const $=id=>document.getElementById(id);let rfb;
async function check(){try{const r=await fetch('/api/vnc-status');if(r.status===401){location.href='/';return;}const s=await r.json();$('connect').disabled=!s.available;$('info').textContent=s.available?'VNC 服务已启动。请输入单独配置的 VNC 密码。':'当前 Mac 尚未启动 VNC 服务。原网页桌面仍可使用；需要在启动流程配置 MACOS_VNC_PASSWORD。';}catch(e){$('info').textContent='检查连接失败，请稍后重试';}}
$('connect').onclick=()=>{rfb?.disconnect();const credentials={password:$('vncPassword').value};$('vncPassword').value='';$('info').textContent='正在连接…';rfb=new RFB($('view'),`${location.protocol==='https:'?'wss':'ws'}://${location.host}/vnc-socket`,{credentials});rfb.scaleViewport=true;rfb.resizeSession=false;rfb.qualityLevel=4;rfb.compressionLevel=6;rfb.addEventListener('connect',()=>{$('info').textContent='VNC 已连接 · 点击桌面即可操作';});rfb.addEventListener('disconnect',e=>{$('info').textContent=e.detail.clean?'VNC 已断开':'VNC 连接中断，请检查服务和密码';});rfb.addEventListener('credentialsrequired',()=>{$('info').textContent='请重新输入 VNC 密码并连接。';rfb.disconnect();});rfb.addEventListener('securityfailure',()=>{$('info').textContent='VNC 身份验证失败，请检查单独的 VNC 密码';});};
$('disconnect').onclick=()=>rfb?.disconnect();$('full').onclick=()=>$('view').requestFullscreen();check();'''

def ready():
    try:
        with socket.create_connection(('127.0.0.1', VNC_PORT), timeout=1) as s:
            s.settimeout(1)
            return s.recv(12).startswith(b'RFB ')
    except OSError:
        return False

def route(handler, path):
    if path == '/vnc':
        if not handler.session():
            handler.reply(302, b'', headers={'Location':'/'})
            return True
        handler.reply(200, HTML, 'text/html; charset=utf-8')
        return True
    if path not in {'/vnc.js', '/vnc.css', '/api/vnc-status'} and not path.startswith('/vnc-static/'):
        return False
    if not handler.session():
        handler.reply(401, {'error':'authentication required'})
    elif path == '/vnc.js':
        handler.reply(200, JS, 'text/javascript; charset=utf-8')
    elif path == '/vnc.css':
        handler.reply(200, CSS, 'text/css; charset=utf-8')
    elif path == '/api/vnc-status':
        handler.reply(200, {'available':ready()})
    else:
        root = Path(__file__).resolve().parent/'novnc'
        target = (root/unquote(path.removeprefix('/vnc-static/'))).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file() or target.suffix not in {'.js', '.css', '.png', '.svg', '.json'}:
            handler.reply(404, {'error':'not found'})
        else:
            handler.reply(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
    return True

def upgrade(handler):
    """Only proxy authenticated, same-origin requests to the local VNC port."""
    token = handler.session()
    if not token:
        return handler.reply(401, {'error':'authentication required'})
    origin = urlsplit(handler.headers.get('Origin', ''))
    if origin.scheme not in {'http', 'https'} or origin.netloc != handler.headers.get('Host') or origin.path or origin.query or origin.fragment:
        return handler.reply(403, {'error':'same origin required'})
    try:
        from websockify.websocketserver import HttpWebSocket
        from websockify.websocket import WebSocketWantReadError, WebSocketWantWriteError
        target = socket.create_connection(('127.0.0.1',VNC_PORT),timeout=1)
    except (ImportError, OSError):
        return handler.reply(503, {'error':'VNC unavailable'})
    class BinarySocket(HttpWebSocket):
        def select_subprotocol(self, protocols):
            return 'binary' if 'binary' in protocols else ''
    ws = BinarySocket(handler)
    handler.close_connection = True
    try:
        ws.accept(handler.connection, handler.headers)
        handler.connection.settimeout(3)
        target.settimeout(3)
        d = handler.server.desktop
        while not d.finished.is_set() and time.time() < d.deadline and handler.session():
            readable, _, _ = select.select([handler.connection,target],[],[],1)
            if handler.connection in readable or ws.pending():
                try:
                    data = ws.recv()
                    if data is None: break
                    if isinstance(data,str): break
                    if data: target.sendall(data)
                except WebSocketWantReadError:
                    pass
            if target in readable:
                data = target.recv(65536)
                if not data: break
                ws.sendmsg(data)
    except (OSError, ValueError, WebSocketWantWriteError):
        pass
    finally:
        target.close()
        try: ws.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError): pass
