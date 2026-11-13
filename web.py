"""Página do overlay para celular/segundo monitor (rede local), servida pelo próprio widget.

Funciona com o jogo em tela cheia exclusiva porque nada é desenhado no PC do jogo: o navegador de outro aparelho
consulta os números por HTTP. Protegida por um link com chave secreta; só escuta quando ativada nos Ajustes.
"""
from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGINA = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Monitor de Hardware</title><style>
:root{--bg:#1a1d24;--txt:#fff;--cpu:#f6a41a;--gpu:#b05ce8;--bat:#58c434;--fps:#ba68ff}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#78909f,#463c32);min-height:100vh;color:var(--txt);font:700 16px/1.2 Bahnschrift,'Arial Narrow',system-ui,sans-serif;padding:max(10px,env(safe-area-inset-top)) 12px 24px;text-transform:uppercase}
.t,.n,.v,.fps *,.info,.rodape,.aviso,.sub{text-shadow:-1.5px -1.5px 0 #000,1.5px -1.5px 0 #000,-1.5px 1.5px 0 #000,1.5px 1.5px 0 #000,0 2px 4px #000}
h1{font-size:22px;text-align:center;margin:6px 0 8px;font-weight:700;text-shadow:-1.5px -1.5px 0 #000,1.5px -1.5px 0 #000,-1.5px 1.5px 0 #000,1.5px 1.5px 0 #000}
.fps{display:flex;align-items:flex-end;gap:12px;padding:0 2px}.fps>span{font-size:54px;line-height:1}.fps b{font-size:54px;line-height:1;color:var(--fps)}
.fps small{display:block;font-size:12px}.fps .m{font-size:13px;line-height:1.5;margin-bottom:6px}.fps .r{margin-left:auto;margin-bottom:6px;font-size:16px}
canvas{width:100%;height:30px;display:block;margin:2px 0 8px}.aviso{color:var(--cpu);text-align:center;font-size:14px;padding:8px}
.barra{position:relative;height:42px;margin:8px 0 6px}.barra i{position:absolute;inset:0 auto 0 0;display:block}
.barra .n,.barra .v{position:absolute;top:0;bottom:0;display:flex;align-items:center;font-size:20px}.barra .n{left:8px}.barra .v{right:2px}
.barra.fina{height:26px;margin:0 0 8px}.barra.fina .n,.barra.fina .v{font-size:13px}.barra.fina .w{position:absolute;inset:0 auto 0 0;display:block}
.info{display:flex;justify-content:space-between;font-size:18px;margin:2px 2px 10px}.rodape{display:flex;justify-content:space-between;font-size:11px;color:#d7d7d7;margin-top:12px}
</style></head><body><h1 id="t">MONITOR DE HARDWARE</h1><div id="c">Conectando…</div>
<script>
const T=new URLSearchParams(location.search).get('t')||'';let hist=[];
const f=(n,d=0)=>n==null?'--':Number(n).toFixed(d);
function temp(c,u){if(c==null)return null;return u==='F'?Math.round(c*9/5+32)+'°F':Math.round(c)+'°C'}
function barra(nome,pct,cor,val){pct=Math.max(0,Math.min(100,pct||0));return `<div class="barra"><i style="width:${pct}%;background:${cor}"></i><span class="n">${nome}</span><span class="v">${val}</span></div>`}
function fina(rot,dir,pct,cor){pct=Math.max(0,Math.min(100,pct||0));return `<div class="barra fina"><i style="width:${pct*0.78}%;background:${cor}"></i><span class="n">${rot}</span><span class="v">${dir}</span></div>`}
function ex(a){return a.filter(Boolean).join(' &nbsp; ')}
function render(d){
 const u=d.unidade,F=d.fps;let h='';if(d.exclusiva)h+='<div class="aviso">TELA CHEIA EXCLUSIVA: NO PC, USE JANELA SEM BORDAS PARA VER O OVERLAY</div>';
 document.getElementById('t').textContent=(d.aparelho||'MONITOR DE HARDWARE').toUpperCase();
 if(F){hist.push(F.frametime);if(hist.length>120)hist.shift();
  h+=`<div class="fps"><span>FPS</span><b>${f(F.fps)}</b><div class="m">MEDIA ${f(F.media)}<br>1% LOW ${f(F.low1)}</div><div class="r">${f(F.frametime,1).replace('.',',')} MS</div></div><canvas id="g" width="600" height="60"></canvas>`}
 else{const m={permissao:'FPS requer permissao no PC (veja o README)',indisponivel:'FPS indisponivel (PresentMon ausente)',sem_dados:'FPS sem quadros (tela cheia exclusiva?)',iniciando:'FPS iniciando…',parado:'Aguardando jogo…',erro:'FPS: erro no PresentMon'};
  h+=`<div class="aviso">${m[d.estado_fps]||'FPS indisponível'}</div>`}
 const C=d.cpu;if(C){h+=barra(C.nome,C.uso,'var(--cpu)',f(C.uso)+'%');
  if(d.ram)h+=fina(f(d.ram.usada,1)+'/'+f(d.ram.total)+' GB RAM',f(d.ram.pct)+'%',d.ram.pct,'var(--cpu)');
  h+=`<div class="info">${ex([C.temp!=null?(C.aprox?'≈':'')+temp(C.temp,u):null,C.mhz?f(C.mhz)+' MHz':null,C.watts!=null?f(C.watts)+' W':null])}</div>`}
 for(const g of d.gpus||[]){ if(g.uso==null)continue;h+=barra(g.nome,g.uso,'var(--gpu)',f(g.uso)+'%');
  if(g.vram_usada!=null){const p=g.vram_total?g.vram_usada/g.vram_total*100:0;h+=fina(f(g.vram_usada,1)+(g.vram_total?'/'+f(g.vram_total):'')+' GB VRAM',g.vram_total?f(p)+'%':'',p,'var(--gpu)')}
  h+=`<div class="info">${ex([g.temp!=null?temp(g.temp,u):null,g.mhz?f(g.mhz)+' MHz':null,g.watts!=null?f(g.watts)+' W':null])}</div>`}
 if(d.bateria)h+=barra(d.bateria.ligada?'BATERIA: CARREGANDO':'BATERIA RESTANTE'+(d.bateria.resta?' · '+Math.floor(d.bateria.resta/3600)+'h'+String(Math.floor(d.bateria.resta%3600/60)).padStart(2,'0'):''),d.bateria.pct,'var(--bat)',f(d.bateria.pct)+'%');
 if(d.fans&&d.fans.length)h+=`<div class="info">${d.fans.map((x,i)=>'Vent '+(i+1)+': '+f(x.rpm)+' rpm').join(' &nbsp; ')}</div>`;
 if(d.rede)h+=`<div class="info"><span>↓ ${d.rede.down}</span><span>↑ ${d.rede.up}</span></div>`;
 h+=`<div class="rodape"><span>${d.jogo?d.jogo.exe.toUpperCase()+(d.jogo.api?' '+d.jogo.api:''):''}</span><span>${d.jogo?'RESOLUCAO: '+d.jogo.larg+'x'+d.jogo.alt:''}</span></div>`;
 document.getElementById('c').innerHTML=h;
 const cv=document.getElementById('g');if(cv&&hist.length>1){const x=cv.getContext('2d'),w=cv.width,hh=cv.height,m=Math.max(16.7,...hist)*1.15;x.strokeStyle='#fff';x.lineWidth=2;x.shadowColor='#000';x.shadowBlur=3;x.beginPath();hist.forEach((v,i)=>{const px=w*i/(hist.length-1),py=hh-hh*Math.min(v,m)/m;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()}
}
async function tick(){try{const r=await fetch('/dados?t='+encodeURIComponent(T),{cache:'no-store'});if(!r.ok)throw 0;render(await r.json())}catch(e){document.getElementById('c').innerHTML='<div class="aviso">Sem conexão com o PC… tentando de novo</div>'}}
tick();setInterval(tick,1000);
try{navigator.wakeLock&&navigator.wakeLock.request('screen')}catch(e){}
</script></body></html>"""


def ip_local() -> str:
    """IP da rede local (sem enviar nada: só descobre qual interface sairia para a internet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class ServidorWeb:
    def __init__(self, snapshot, cfg: dict):
        self.snapshot, self.cfg = snapshot, cfg
        self._srv: ThreadingHTTPServer | None = None
        self.erro = ""

    @property
    def ativo(self) -> bool:
        return self._srv is not None

    def url(self) -> str:
        return f"http://{ip_local()}:{self.cfg['porta']}/?t={self.cfg['token']}"

    def novo_token(self):
        self.cfg["token"] = secrets.token_urlsafe(9)

    def iniciar(self) -> bool:
        self.parar()
        if not self.cfg.get("token"):
            self.novo_token()
        serv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencioso
                pass

            def _ok(self) -> bool:
                t = parse_qs(urlparse(self.path).query).get("t", [""])[0]
                return hmac.compare_digest(t, serv.cfg["token"])

            def do_GET(self):
                rota = urlparse(self.path).path
                if not self._ok():
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b"link invalido")
                    return
                if rota == "/dados":
                    corpo, tipo = json.dumps(serv.snapshot(), ensure_ascii=False).encode(), "application/json; charset=utf-8"
                elif rota in ("/", "/index.html"):
                    corpo, tipo = PAGINA.encode(), "text/html; charset=utf-8"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corpo)

        try:
            self._srv = ThreadingHTTPServer(("0.0.0.0", int(self.cfg["porta"])), H)
        except OSError as e:
            self._srv, self.erro = None, str(e)
            return False
        self.erro = ""
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return True

    def parar(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
