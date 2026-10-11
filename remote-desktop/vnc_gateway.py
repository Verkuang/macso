"""Cookie-protected noVNC on the existing private desktop HTTP endpoint."""
import getpass
import html
import mimetypes
import select
import socket
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit
VNC_PORT = 5900

HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mac 网页 VNC</title><link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/vnc.css"><header><strong>Mac 网页 VNC</strong><a href="/">原网页桌面</a><span class="spacer"></span><label for="authMode">登录方式</label><select id="authMode"><option value="account">系统账户</option><option value="vnc">VNC 密码</option></select><label for="macUsername">用户名</label><input id="macUsername" value="__DEFAULT_USERNAME__" readonly aria-readonly="true"><label id="passwordLabel" for="vncPassword">系统账户密码</label><input id="vncPassword" type="password" autocomplete="off"><button id="connect">连接</button><button id="disconnect">断开</button><button id="full">全屏</button></header><div id="authHint">用户名已自动填写。请输入这个账户的 macOS 系统密码。</div><div id="info" role="status">正在检查 VNC 服务…</div><div id="view"></div><script type="module" src="/vnc.js"></script></html>'''

CSS = '#view{height:calc(100vh - 175px);background:#05080c}#info,#authHint{padding:8px 12px;color:#b6c7de}header{flex-wrap:wrap}header input{width:160px}#macUsername{width:90px}header select{padding:8px;background:#111d30;color:#fff;border:1px solid #33435d;border-radius:6px}[hidden]{display:none!important}'

JS = '''import RFB from '/vnc-static/core/rfb.js';
// Pin each connection to the requested authenticated mode; never fall back to no-auth.
class AuthRFB extends RFB {
    constructor(target, url, options, mode) {
        super(target, url, options);
        this.securityType = mode === 'account' ? 30 : 2;
    }
    _isSupportedSecurityType(type) { return type === this.securityType; }
    _negotiateAuthentication() {
        if (this._rfbAuthScheme !== this.securityType) {
            return this._fail('The server did not offer the selected authentication mode.');
        }
        return super._negotiateAuthentication();
    }
}
const $ = id => document.getElementById(id);
let rfb, available = false;
function updateMode() {
    const account = $('authMode').value === 'account';
    $('macUsername').hidden = !account;
    document.querySelector('label[for="macUsername"]').hidden = !account;
    $('passwordLabel').textContent = account ? '系统账户密码' : 'VNC 密码';
    $('vncPassword').value = '';
    if (account) $('vncPassword').removeAttribute('maxlength');
    else $('vncPassword').maxLength = 8;
    $('authHint').textContent = account ?
        '用户名已自动填写。请输入这个账户的 macOS 系统密码；它可能与 VNC 密码不同。' :
        '请输入单独配置的 VNC 密码。这种方式不负责登录 macOS 系统账户。';
}
async function check() {
    try {
        const r = await fetch('/api/vnc-status');
        if (r.status === 401) { location.href = '/'; return; }
        if (!r.ok) throw new Error('unavailable');
        available = (await r.json()).available;
        $('connect').disabled = !available;
        $('info').textContent = available ? '服务已就绪，请输入对应密码后连接。' :
            '当前 Mac 尚未启动 VNC 服务，原网页桌面仍可使用。';
    } catch (e) {
        available = false;
        $('connect').disabled = true;
        $('info').textContent = '检查连接失败，请稍后刷新重试。';
    }
}
$('authMode').onchange = () => {
    const old = rfb; rfb = null; old?.disconnect();
    updateMode();
    $('info').textContent = available ? '请选择的方式输入密码后连接。' : 'VNC 服务暂不可用。';
};
$('connect').onclick = () => {
    const mode = $('authMode').value, password = $('vncPassword').value;
    if (!password) { $('info').textContent = '请先输入对应密码。'; return; }
    if (mode === 'vnc' && password.length > 8) {
        $('info').textContent = 'VNC 密码最多 8 位；系统密码请使用系统账户方式。'; return;
    }
    const credentials = mode === 'account' ?
        { username: $('macUsername').value, password } : { password };
    const old = rfb; rfb = null; old?.disconnect();
    $('vncPassword').value = '';
    $('info').textContent = '正在连接…';
    const next = new AuthRFB($('view'),
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/vnc-socket`,
        { credentials, shared: true }, mode);
    rfb = next;
    next.scaleViewport = true;
    next.resizeSession = false;
    next.qualityLevel = 4;
    next.compressionLevel = 6;
    next.addEventListener('connect', () => {
        if (rfb === next) $('info').textContent =
            '连接已建立，请确认下方是否显示已有桌面。';
    });
    let failed = false;
    next.addEventListener('disconnect', e => {
        if (rfb !== next || failed) return;
        $('info').textContent = e.detail.clean ? '连接已断开。' : '连接中断，请重试。';
    });
    next.addEventListener('credentialsrequired', () => {
        if (rfb !== next) return;
        failed = true;
        $('info').textContent = '服务器要求其他认证信息，请检查当前登录方式。';
        next.disconnect();
    });
    next.addEventListener('securityfailure', () => {
        if (rfb !== next) return;
        failed = true;
        $('info').textContent = mode === 'account' ?
            '系统账户认证失败，请检查当前账户的系统密码。' :
            'VNC 密码认证失败，请检查单独配置的 VNC 密码。';
    });
};
$('disconnect').onclick = () => rfb?.disconnect();
$('full').onclick = () => $('view').requestFullscreen();
updateMode();
check();
'''

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
        handler.reply(200, HTML.replace('__DEFAULT_USERNAME__', html.escape(getpass.getuser(), quote=True)), 'text/html; charset=utf-8')
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
