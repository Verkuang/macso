"""Private, short-lived macOS browser desktop. No arbitrary shell endpoint."""
import collections
import hmac
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>临时 Mac 桌面</title><link rel="stylesheet" href="/style.css"></head><body>
<section id="login"><div class="card"><div class="icon">▣</div><h1>临时 Mac 桌面</h1><p>登录后查看和操作项目测试环境。</p><form id="loginForm"><label for="password">桌面密码</label><input id="password" type="password" autocomplete="current-password" required autofocus><button>进入桌面</button><p id="loginError" role="alert"></p></form></div></section>
<main id="desktop" hidden><header><strong>临时 Mac 桌面</strong><span id="connection" role="status">正在连接…</span><span class="spacer"></span><span id="remaining"></span><button id="fullscreen">全屏</button><button id="logout">退出查看</button><button id="end" class="danger">结束会话</button></header>
<nav aria-label="桌面工具"><button data-app="Finder">访达</button><button data-app="Safari">浏览器</button><button data-app="Xcode">Xcode</button><button data-app="Simulator">模拟器</button><span class="spacer"></span><button data-key="Enter">回车</button><button data-key="Escape">Esc</button><button data-key="Tab">Tab</button><button id="cmdspace">启动搜索</button><a href="/frame.jpg" download="macos-desktop.jpg">保存截图</a></nav>
<div id="notice" role="status"></div><section id="stage" aria-label="远程画面"><img id="screen" alt="macOS 实时桌面，点击后可使用键盘" tabindex="0" draggable="false"></section>
<footer><label for="text">发送文字</label><input id="text" placeholder="可输入中文、网址或测试文字"><button id="sendText">发送到光标位置</button><span id="message" role="status">点击桌面即可操作鼠标和键盘</span></footer></main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}body{margin:0;background:#0b0f17;color:#ecf0f7;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,a,input{font:inherit}button,a{border:1px solid #344158;border-radius:8px;background:#1c2738;color:#e9f0ff;padding:9px 13px;cursor:pointer;text-decoration:none}button:hover,a:hover{background:#2b3c58}button:disabled{opacity:.4;cursor:default}input{border:1px solid #344158;background:#0c1525;border-radius:8px;color:white;padding:11px;outline:none}input:focus{border-color:#6f9aff}#login{min-height:100vh;display:grid;place-items:center}.card{width:min(410px,92vw);padding:35px;border:1px solid #29364a;border-radius:20px;background:#121d2d;box-shadow:0 30px 90px #0007}.icon{font-size:40px;color:#81aaff}h1{font-size:26px;margin:16px 0 10px}p{color:#a8b6ca;line-height:1.6}form{display:grid;gap:12px;margin-top:25px}form button{background:#4779e8;font-weight:600}#loginError{margin:0;color:#ffb1b1}header,nav,footer{display:flex;gap:10px;align-items:center;padding:12px 18px;border-bottom:1px solid #243045;flex-wrap:wrap}header strong{font-size:17px}#connection{font-size:12px;color:#a9caff}.spacer{flex:1}.danger{color:#ffb8b8;border-color:#744048}#remaining{color:#a8b6ca;font-size:12px}nav{padding-block:8px}#notice{color:#e7c67a;text-align:center;font-size:12px;padding:4px;min-height:25px}#stage{height:calc(100vh - 188px);min-height:200px;display:flex;align-items:center;justify-content:center;background:#030609;overflow:hidden}#screen{max-width:100%;max-height:100%;width:auto;height:auto;outline:none;user-select:none;cursor:crosshair;touch-action:none}#screen:focus{box-shadow:inset 0 0 0 2px #5788f9}footer{border-top:1px solid #243045;border-bottom:0}footer input{flex:1;min-width:180px}#message{font-size:12px;color:#a8b6ca}[hidden]{display:none!important}@media(max-width:700px){#stage{height:calc(100vh - 270px)}header,nav,footer{padding:8px}#message{width:100%}}'''
JS = r'''const $=id=>document.getElementById(id);let csrf='',active=false,canControl=false,mouseButton=0,drag=false,lastMove=0,inputQueue=Promise.resolve(),lastClick=null;const pressed=new Set();
async function api(path,data){const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-Desktop-CSRF':csrf},body:data===undefined?undefined:JSON.stringify(data)});if(!r.ok){if(r.status===401){active=false;$('login').hidden=false;$('desktop').hidden=true;}throw new Error(r.status===401?'请重新登录':r.status===429?'操作过于频繁，请稍后重试':'操作失败，请检查连接');}return r.json();}
function notify(text){$('message').textContent=text;}function input(data){if(!canControl)return Promise.resolve();inputQueue=inputQueue.then(async()=>{try{await api('/api/input',data);}catch(e){notify(e.message);}});return inputQueue;}
async function start(){try{const s=await api('/api/status');csrf=s.csrf;canControl=s.control;active=true;$('login').hidden=true;$('desktop').hidden=false;$('notice').textContent=canControl?'':'当前只允许查看画面，系统尚未允许鼠标和键盘操作。';document.querySelectorAll('[data-app],[data-key],#sendText,#cmdspace').forEach(b=>b.disabled=!canControl);$('remaining').textContent='剩余 '+Math.max(0,Math.ceil(s.remaining/60))+' 分钟';refresh();}catch(e){$('loginError').textContent=e.message;}}
function refresh(){if(active)$('screen').src='/frame.jpg?t='+Date.now();}$('screen').onload=()=>{$('connection').textContent='画面已连接'+(canControl?' · 可操作':' · 仅查看');if(active)setTimeout(refresh,650);};$('screen').onerror=()=>{$('connection').textContent='画面连接中断';if(active)setTimeout(refresh,1800);};
$('loginForm').onsubmit=async e=>{e.preventDefault();$('loginError').textContent='';try{await api('/api/login',{password:$('password').value});$('password').value='';await start();}catch(e){$('loginError').textContent=e.message;}};
function position(e){const r=$('screen').getBoundingClientRect();return{x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};}
$('screen').onpointerdown=e=>{if(!canControl)return;e.preventDefault();$('screen').focus();$('screen').setPointerCapture(e.pointerId);drag=true;mouseButton=e.button;const p=position(e),now=Date.now();const clicks=lastClick&&now-lastClick.time<450&&Math.abs(p.x-lastClick.x)<.005&&Math.abs(p.y-lastClick.y)<.005&&e.button===lastClick.button?2:1;lastClick={...p,time:now,button:e.button};input({type:'mouse',action:'down',button:e.button,clicks,...p});};
$('screen').onpointerup=e=>{if(!canControl)return;e.preventDefault();drag=false;input({type:'mouse',action:'up',button:mouseButton,clicks:Math.min(2,e.detail||1),...position(e)});};
$('screen').onpointermove=e=>{if(!canControl||Date.now()-lastMove<60)return;lastMove=Date.now();input({type:'mouse',action:'move',button:mouseButton,drag,...position(e)});};$('screen').oncontextmenu=e=>e.preventDefault();$('screen').addEventListener('wheel',e=>{if(!canControl)return;e.preventDefault();input({type:'scroll',dx:Math.round(e.deltaX),dy:Math.round(e.deltaY)});},{passive:false});
function key(e,down){if(!canControl)return;e.preventDefault();if(down)pressed.add(e.code);else pressed.delete(e.code);input({type:'key',code:e.code,down,shift:e.shiftKey,ctrl:e.ctrlKey,alt:e.altKey,meta:e.metaKey});}$('screen').onkeydown=e=>key(e,true);$('screen').onkeyup=e=>key(e,false);$('screen').onblur=()=>{for(const code of pressed)input({type:'key',code,down:false});pressed.clear();};
async function tap(code,meta=false){await input({type:'key',code,down:true,meta});await input({type:'key',code,down:false});$('screen').focus();}document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>tap(b.dataset.key));$('cmdspace').onclick=()=>tap('Space',true);
document.querySelectorAll('[data-app]').forEach(b=>b.onclick=async()=>{try{await api('/api/launch',{app:b.dataset.app});notify('正在打开 '+b.textContent);$('screen').focus();}catch(e){notify(e.message);}});
$('sendText').onclick=async()=>{if(!$('text').value)return;await input({type:'text',text:$('text').value});$('text').value='';$('screen').focus();};$('text').onkeydown=e=>{if(e.key==='Enter')$('sendText').click();};
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('desktop').requestFullscreen();};$('logout').onclick=async()=>{await api('/api/logout',{});active=false;$('desktop').hidden=true;$('login').hidden=false;};$('end').onclick=async()=>{if(!confirm('结束后这台临时 Mac 会关闭。确认结束会话？'))return;await api('/api/end',{});active=false;$('connection').textContent='会话已结束';canControl=false;};
setInterval(async()=>{if(!active)return;try{const s=await api('/api/status');$('remaining').textContent='剩余 '+Math.max(0,Math.ceil(s.remaining/60))+' 分钟';}catch(e){notify(e.message);}},20000);start();'''

class Desktop:
    def __init__(self, helper, password, minutes):
        self.password = password.encode()
        self.deadline = time.time() + minutes * 60
        self.capabilities = json.loads(subprocess.check_output([str(helper), '--status']))
        if not self.capabilities['capture']:
            raise RuntimeError('The runner does not allow screen capture.')
        self.process = subprocess.Popen([str(helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.input_lock = threading.Lock()
        self.frame_lock = threading.Lock()
        self.session_lock = threading.Lock()
        self.sessions = {}
        self.attempts = collections.defaultdict(collections.deque)
        self.frame = None
        self.frame_time = 0
        self.finished = threading.Event()
        threading.Thread(target=self.capture, daemon=True).start()

    def capture(self):
        with tempfile.TemporaryDirectory(prefix='web-desktop-') as folder:
            path = Path(folder)/'frame.jpg'
            while not self.finished.is_set() and time.time() < self.deadline:
                try:
                    subprocess.run(['/usr/sbin/screencapture', '-x', '-C', '-t', 'jpg', str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    data = path.read_bytes()
                    if data.startswith(b'\xff\xd8'):
                        with self.frame_lock:
                            self.frame, self.frame_time = data, time.time()
                except (OSError, subprocess.SubprocessError):
                    pass
                self.finished.wait(0.6)
        self.finished.set()

    def command(self, data):
        if not self.capabilities['control']:
            return False
        with self.input_lock:
            self.process.stdin.write(json.dumps(data)+'\n')
            self.process.stdin.flush()
            return json.loads(self.process.stdout.readline()).get('ok', False)

class Handler(BaseHTTPRequestHandler):
    server_version = 'PrivateDesktop'
    def log_message(self, *args):
        pass  # Never log passwords, cookies, typed text, or query strings.

    def reply(self, code, data, mime='application/json', headers=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def session(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie',''))
            token = cookies['desktop-session'].value
        except (KeyError, ValueError):
            return None
        with self.server.desktop.session_lock:
            expiry = self.server.desktop.sessions.get(token, 0)
        return token if expiry > time.time() else None

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == '/': return self.reply(200, HTML, 'text/html; charset=utf-8')
        if route == '/style.css': return self.reply(200,CSS,'text/css; charset=utf-8')
        if route == '/app.js': return self.reply(200,JS,'text/javascript; charset=utf-8')
        d = self.server.desktop
        if route == '/health': return self.reply(200, {'ready':d.frame is not None})
        token = self.session()
        if not token: return self.reply(401, {'error':'authentication required'})
        if route == '/api/status':
            return self.reply(200, {'control':d.capabilities['control'], 'csrf':token, 'remaining':max(0,int(d.deadline-time.time())), 'frameAge':max(0,time.time()-d.frame_time)})
        if route == '/frame.jpg':
            with d.frame_lock:
                data = d.frame
            return self.reply(200,data,'image/jpeg') if data else self.reply(503, {'error':'frame not ready'})
        return self.reply(404, {'error':'not found'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error':'invalid origin'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 16384: raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError()
        except (ValueError, json.JSONDecodeError):
            return self.reply(400, {'error':'invalid request'})
        d = self.server.desktop
        route = urlsplit(self.path).path
        if route == '/api/login':
            if not isinstance(data.get('password'),str): return self.reply(400, {'error':'invalid request'})
            with d.session_lock:
                attempts = d.attempts[self.client_address[0]]
                while attempts and attempts[0] < time.time()-60: attempts.popleft()
                if len(attempts) >= 5: return self.reply(429, {'error':'try later'})
                if not hmac.compare_digest(data['password'].encode(),d.password):
                    attempts.append(time.time())
                    return self.reply(401, {'error':'invalid credentials'})
                attempts.clear()
                token = secrets.token_urlsafe(32)
                d.sessions[token] = d.deadline
            return self.reply(200, {'ok':True}, headers={'Set-Cookie':f'desktop-session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max(1,int(d.deadline-time.time()))}'})
        token = self.session()
        if not token: return self.reply(401, {'error':'authentication required'})
        if not hmac.compare_digest(self.headers.get('X-Desktop-CSRF',''),token):
            return self.reply(403, {'error':'invalid csrf token'})
        if route == '/api/input':
            if data.get('type') not in {'mouse','key','text','scroll'}: return self.reply(400, {'error':'invalid input'})
            try:
                ok = d.command(data)
            except (OSError,ValueError):
                ok = False
            return self.reply(200 if ok else 403, {'ok':ok})
        if route == '/api/launch':
            names = {'Finder','Safari','Xcode','Simulator'}
            if data.get('app') not in names: return self.reply(400, {'error':'unsupported app'})
            if not d.capabilities['control']: return self.reply(403, {'error':'control not permitted'})
            try:
                subprocess.run(['/usr/bin/open','-a',data['app']], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (OSError,subprocess.SubprocessError): return self.reply(503, {'error':'app unavailable'})
            return self.reply(200, {'ok':True})
        if route == '/api/logout':
            with d.session_lock: d.sessions.pop(token,None)
            return self.reply(200, {'ok':True}, headers={'Set-Cookie':'desktop-session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
        if route == '/api/end':
            self.reply(200, {'ok':True})
            d.finished.set()
            return
        return self.reply(404, {'error':'not found'})

def main():
    password = os.environ.pop('MACOS_PASSWORD', '')
    if not password: raise RuntimeError('MACOS_PASSWORD is required.')
    folder = Path(__file__).resolve().parent
    d = Desktop(folder/'input-helper',password,int(os.environ.get('SESSION_MINUTES','30')))
    server = ThreadingHTTPServer(('127.0.0.1',6080), Handler)
    server.desktop = d
    print(json.dumps({'capture':d.capabilities['capture'],'control':d.capabilities['control'],'listen':'127.0.0.1:6080'}), flush=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        while not d.finished.wait(1) and time.time() < d.deadline: pass
    finally:
        d.finished.set()
        server.shutdown()
        server.server_close()
        d.process.terminate()
        d.process.wait(timeout=5)

if __name__ == '__main__': main()
