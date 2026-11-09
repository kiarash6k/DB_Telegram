"""Departure-board widget (Telegram Bot API 10.4).

The widget is static HTML with no network access. The bot passes data in as JSON
(``chat_data`` when sending, and as the answer to a refresh query). Both are
limited to 1024 bytes, so the payload is kept compact.
"""
from __future__ import annotations

import json
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .api import BERLIN, Departure, Journey

MAX_DATA_BYTES = 1024
MAX_HTML_COMPRESSED = 4096

WIDGET_HTML = r"""<style>
:root{--bg:#f0f3f5;--card:#fff;--fg:#282d37;--mut:#687787;--line:#dfe4e8;--red:#ec0016}
.dark{--bg:#1c2028;--card:#282d37;--fg:#fff;--mut:#aab0b8;--line:#3b4250}
*{box-sizing:border-box}
body{margin:0;padding:6px;background:var(--bg);color:var(--fg);font:14px/1.25 -apple-system,system-ui,"Segoe UI",sans-serif}
.card{background:var(--card);border-radius:22px;overflow:hidden;box-shadow:0 1px 4px #0002}
.h{display:flex;align-items:center;gap:10px;padding:13px 14px;background:var(--red);color:#fff}
.n{flex:1;min-width:0}
.n b{display:block;font-size:17px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.n small{opacity:.85;font-size:11px}
button{border:0;border-radius:16px;min-height:32px;padding:0 14px;background:#fff;color:var(--red);font:700 13px system-ui}
button:active{transform:scale(.96)}button:disabled{opacity:.55}
.r{display:flex;align-items:center;gap:8px;margin:6px 8px;padding:8px 10px;background:var(--bg);border-radius:16px}
.tm{min-width:48px;text-align:center}
.tm b{display:block;font-size:16px;font-variant-numeric:tabular-nums}
.dl{display:inline-block;margin-top:2px;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:700}
.dl.s{background:#fff1c2;color:#7a5600}.dl.m{background:#ffd9b8;color:#8a3b00}.dl.l{background:#ffd0d4;color:#b0000f}
.bd{padding:3px 9px;border-radius:11px;background:#646973;color:#fff;font-size:12px;font-weight:700;white-space:nowrap}
.bd.hs{background:var(--red)}.bd.sb{background:#1e8f4e}.bd.re{background:#3b4351}
.ds{flex:1;min-width:0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pl{padding:3px 9px;border-radius:11px;background:var(--card);border:1px solid var(--line);font-size:12px;font-weight:700;white-space:nowrap}
.pl.ch{background:#fff1c2;border-color:#f0c36d;color:#7a5600}
.pl.cx{background:#ffd0d4;border-color:#ffd0d4;color:#b0000f}
.c .tm b,.c .ds{text-decoration:line-through;opacity:.55}
.em{padding:26px 14px;text-align:center;color:var(--mut)}
.f{padding:6px 16px 13px;color:var(--mut);font-size:11px}
</style>
<div class=card><div class=h><div class=n><b id=s>Departures</b><small id=u></small></div><button id=b>Refresh</button></div>
<div id=l></div><div class=f id=f>Data: Transitous</div></div>
<script>
var W=window.TelegramWidget,$=function(i){return document.getElementById(i)},busy=0;
function el(p,c,t){var e=document.createElement('span');e.className=c;e.textContent=t;p.appendChild(e);return e}
function badge(n){return /^(ICE|IC|EC|RJX?|NJ|TGV|THA)/.test(n)?'hs':/^S\d/.test(n)?'sb':/^(RE|RB|IRE|RS)/.test(n)?'re':''}
function draw(x){
  var L=$('l'),d=Array.isArray(x.d)?x.d.slice(0,20):[];
  $('s').textContent=String(x.s||'Departures');
  $('u').textContent=x.t?'Updated '+x.t:'';
  L.textContent='';
  if(!d.length){var e=document.createElement('div');e.className='em';e.textContent='No departures right now';L.appendChild(e);return}
  d.forEach(function(r){
    var w=document.createElement('div'),dl=+r[1]||0;w.className='r'+(r[5]?' c':'');
    var t=document.createElement('div');t.className='tm';
    var b=document.createElement('b');b.textContent=String(r[0]);t.appendChild(b);
    if(dl>0&&!r[5])el(t,'dl '+(dl<5?'s':dl<15?'m':'l'),'+'+dl);
    w.appendChild(t);
    el(w,'bd '+badge(String(r[2])),String(r[2]));
    el(w,'ds',String(r[3]));
    if(r[5])el(w,'pl cx','Cancelled');
    else if(r[4])el(w,'pl'+(r[6]?' ch':''),'Pl. '+r[4]);
    L.appendChild(w)
  })
}
function load(raw){try{draw(JSON.parse(raw||'{}'))}catch(e){$('l').textContent='';$('u').textContent='';
  var m=document.createElement('div');m.className='em';m.textContent='No data. Send /board again.';$('l').appendChild(m)}}
function theme(){document.documentElement.className=W&&W.colorScheme==='dark'?'dark':''}
function note(t){$('f').textContent=t}
if(W){
  theme();load(W.chatData);
  try{W.onEvent('chatDataChanged',function(){load(W.chatData)});W.onEvent('themeChanged',theme)}catch(e){}
  if(W.ready)try{W.ready()}catch(e){}
  $('b').onclick=function(){
    if(busy)return;busy=1;$('b').disabled=true;note('Refreshing...');
    var done=function(m){busy=0;$('b').disabled=false;note(m)};
    var t=setTimeout(function(){done('Timed out. Try again.')},15000);
    try{W.request('r').then(function(a){clearTimeout(t);if(busy){load(a&&a.result);done('Data: Transitous')}},
      function(e){clearTimeout(t);done('Refresh failed ('+(e&&e.code||'error')+')')})}
    catch(e){clearTimeout(t);done('Refresh failed')}
  }
}else{load('{}');$('b').style.display='none';note('Open this in Telegram')}
</script>"""


def encode_board(station: str, deps: list[Departure], now: datetime | None = None) -> str:
    """Compact JSON for the widget: {"s": station, "t": "HH:MM", "d": [rows]}.

    Row = [planned "HH:MM", delay min, line, direction, platform, cancelled 0/1, platform changed 0/1].
    Rows are dropped from the end until the payload fits in 1024 bytes.
    """
    now = now or datetime.now(BERLIN)
    rows = [
        [
            d.planned.strftime("%H:%M") if d.planned else "--:--",
            max(d.delay_min, 0),
            d.line[:10],
            d.direction[:30],
            d.platform or "",
            int(d.cancelled),
            int(bool(d.platform and d.planned_platform and d.platform != d.planned_platform)),
        ]
        for d in deps
    ]
    payload = {"s": station[:30], "t": now.strftime("%H:%M"), "d": rows}
    while True:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode()) <= MAX_DATA_BYTES or not rows:
            return text
        rows.pop()


def html_fits(html: str = WIDGET_HTML) -> bool:
    return len(zlib.compress(html.encode(), 9)) <= MAX_HTML_COMPRESSED


TRIP_HTML = r"""<style>
:root{--bg:#f0f3f5;--cd:#fff;--fg:#282d37;--mu:#687787;--ln:#dfe4e8;--red:#ec0016}
.dark{--bg:#1c2028;--cd:#252a34;--fg:#fff;--mu:#aab0b8;--ln:#3b4250}
*{box-sizing:border-box}
body{margin:0;padding:6px;background:var(--bg);color:var(--fg);font:14px/1.25 -apple-system,system-ui,"Segoe UI",sans-serif}
.card{border-radius:26px;overflow:hidden;background:var(--cd);box-shadow:0 2px 8px #0003}
.hero{padding:16px 14px 12px;color:#fff;background:radial-gradient(120% 90% at 100% 0,#ff3b4e 0,#ec0016 38%,#8e0012 100%)}
.top{display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px}
.top span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ic{border:0;width:34px;height:34px;border-radius:17px;background:#ffffff2e;color:#fff;font-size:17px}
.big{display:flex;align-items:flex-end;gap:10px;margin:8px 0 2px}
.big i{font:200 58px/1 -apple-system,system-ui,sans-serif;font-style:normal;letter-spacing:-2px}
.big u{text-decoration:none;font-size:15px;font-weight:600;margin-bottom:9px}
.sd{margin:0 0 9px auto;text-align:right}
.sd b{display:block;font-size:14px}
.sub{font-size:13px;opacity:.92;margin:0 0 12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sg{display:flex;gap:5px}.sg div{flex:1 1 0;min-width:0}
.sg s{display:block;height:7px;border-radius:4px;background:#ffffff3a;overflow:hidden}
.sg s i{display:block;height:100%;border-radius:4px;background:#4ade80;transition:width .5s}
.sg .a s i{background:#5eb2ff}
.sg em{display:block;margin-top:5px;font-size:11px;font-style:normal;opacity:.85;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip{display:inline-block;margin-left:5px;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:700;background:#ffffff33;color:#fff}
.chip.s{background:#fff1c2;color:#7a5600}.chip.m{background:#ffd9b8;color:#8a3b00}.chip.l{background:#fff;color:#b0000f}
.strip{display:flex;gap:5px;margin-top:14px;padding:5px;border-radius:24px;background:#ffffff26;border:1px solid #ffffff33}
.ch{flex:1 1 0;min-width:0;padding:8px 2px 7px;border-radius:19px;text-align:center;color:#fff;border:1px solid transparent;background:none;font:inherit}
.ch.on{background:#ffffff3d;border-color:#ffffff80}
.ch small{display:block;font-size:11px;opacity:.85}.ch b{display:block;font-size:15px;margin:2px 0}
.sh{padding:14px 14px 4px}
.st,.lg{display:flex;gap:8px}
.tm{width:46px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.tm .chip{margin:2px 0 0;background:#fff1c2;color:#7a5600;display:block;text-align:center;padding:0 4px}
.tm .chip.m{background:#ffd9b8;color:#8a3b00}.tm .chip.l{background:#ffd0d4;color:#b0000f}
.rl{width:14px;display:flex;flex-direction:column;align-items:center}
.rl i{width:12px;height:12px;border-radius:6px;border:3px solid var(--red);background:var(--cd);flex:none;margin-top:2px}
.rl s{width:3px;flex:1;background:var(--ln);border-radius:2px;margin:1px 0}
.nm{flex:1;min-width:0;padding-bottom:6px;font-weight:600}
.nm small{display:block;font-weight:400;color:var(--mu);font-size:12px}
.lg .nm{font-weight:400;color:var(--mu);padding:2px 0 8px;font-size:12px}
.bd{padding:2px 8px;border-radius:10px;background:#646973;color:#fff;font-weight:700;font-size:12px;margin-right:6px}
.bd.hs{background:var(--red)}.bd.sb{background:#1e8f4e}.bd.re{background:#3b4351}.bd.wk{background:var(--bg);color:var(--mu)}
.pl{margin-left:6px;padding:1px 8px;border-radius:10px;border:1px solid var(--ln);font-size:11px;font-weight:700}
.bar{display:flex;gap:8px;padding:8px 14px 4px}
.bar button{flex:1;min-height:38px;border:0;border-radius:19px;background:var(--bg);color:var(--fg);font:700 13px system-ui}
.bar button.p{background:var(--red);color:#fff}.bar button:disabled{opacity:.5}
.bar button:active,.ic:active{transform:scale(.96)}
.f{padding:6px 16px 14px;color:var(--mu);font-size:11px}
.em{padding:24px 14px;text-align:center;color:var(--mu)}
</style>
<div class=card><div class=hero>
<div class=top><span id=rt>Trip</span><button class=ic id=sw>&#8646;</button></div>
<div class=big><i id=nu>-</i><u id=un></u><div class=sd><b id=lb></b><span id=cp></span></div></div>
<div class=sub id=sb></div><div class=sg id=sg></div><div class=strip id=st></div></div>
<div class=sh id=tl></div>
<div class=bar><button id=rf class=p>Refresh</button><button id=nx>Later &#8250;</button></div>
<div class=f id=f>Data: Transitous</div></div>
<script>
var W=window.TelegramWidget,$=function(i){return document.getElementById(i)},D={i:[]},S=0,t0=Date.now(),busy=0;
function m(s){var p=String(s).split(':');return(+p[0]||0)*60+(+p[1]||0)}
function hm(v){v=((Math.round(v)%1440)+1440)%1440;return('0'+(v/60|0)).slice(-2)+':'+('0'+v%60).slice(-2)}
function du(v){v=Math.max(0,Math.round(v));return v>=60?(v/60|0)+':'+('0'+v%60).slice(-2)+' h':v+' min'}
function mk(p,t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;p.appendChild(e);return e}
function bg(v){v=Math.max(0,Math.round(v));return v>=60?[(v/60|0)+':'+('0'+v%60).slice(-2),'h']:[''+v,'min']}
function sv(d){return d<5?'s':d<15?'m':'l'}
function bc(n){return n=='Walk'?'wk':/^(ICE|IC|EC|RJX?|NJ|TGV|THA)/.test(n)?'hs':/^S\d/.test(n)?'sb':/^(RE|RB|IRE|RS)/.test(n)?'re':''}
function T(L){var p=-1,dp=[],ar=[],u=function(s){var v=m(s);while(v<p)v+=1440;p=v;return v};
  L.forEach(function(l){dp.push(u(l[2])+(+l[3]||0));ar.push(u(l[4])+(+l[5]||0))});return{dp:dp,ar:ar}}
function now(t){var n=m(D.t)+(Date.now()-t0)/60000;if(t.dp[0]-n<-720)n-=1440;else if(t.dp[0]-n>720)n+=1440;return n}
function hero(){
  var L=D.i[S]||[],n=L.length,cp=$('cp'),sg=$('sg');
  $('rt').textContent=(D.o||'')+'  \u2192  '+(D.d||'');cp.textContent='';sg.textContent='';
  if(!n){$('nu').textContent='-';$('un').textContent='';$('lb').textContent='No connection found';$('sb').textContent='Try a later time';return}
  var t=T(L),x=now(t),f=t.dp[0],e=t.ar[n-1],c=L.some(function(l){return l[7]}),k=-1,tr=L.filter(function(l){return l[0]!='Walk'}),l0=tr[0]||L[0];
  L.forEach(function(l,i){if(x>=t.dp[i]&&x<t.ar[i])k=i});
  var nu,un,lb,sb=L.map(function(l){return l[0]}).join('  \u203a  ');
  if(c){nu='\u2715';un='Cancelled';lb='Part of this trip is cancelled'}
  else if(x<f){var q=bg(f-x);nu=q[0];un=q[1];lb='Departs '+L[0][2];if(+L[0][3])mk(cp,'span','chip '+sv(+L[0][3]),'+'+L[0][3]);if(l0[6])mk(cp,'span','chip','Pl. '+l0[6])}
  else if(x>=e){nu='\u2713';un='Arrived';lb='Arrived '+L[n-1][4]}
  else{q=bg(e-x);nu=q[0];un=q[1];lb='Arrives '+L[n-1][4];if(+L[n-1][5])mk(cp,'span','chip '+sv(+L[n-1][5]),'+'+L[n-1][5]);
    if(k>=0)sb='Now \u00b7 '+L[k][0]+' \u2192 '+L[k][1];else{var j=0;while(j<n-1&&t.ar[j]<=x)j++;sb='Change at '+L[j-1<0?0:j-1][1]+' \u00b7 '+L[j][0]+' in '+du(t.dp[j]-x)}}
  $('nu').textContent=nu;$('un').textContent=un;$('lb').textContent=lb;$('sb').textContent=sb;
  L.forEach(function(l,i){var d=mk(sg,'div',k==i?'a':''),b=mk(d,'s'),g=mk(b,'i'),r=t.ar[i]-t.dp[i];
    g.style.width=Math.max(0,Math.min(100,r>0?(x-t.dp[i])/r*100:0))+'%';mk(d,'em','',l[0]);d.style.flexGrow=Math.log(Math.max(r,1)+2)})
}
function strip(){var s=$('st');s.textContent='';
  D.i.forEach(function(L,j){var t=T(L),b=mk(s,'button','ch'+(j==S?' on':'')),tr=L.filter(function(l){return l[0]!='Walk'}).length;
    mk(b,'small','',L[0][2]+(+L[0][3]?' +'+L[0][3]:''));mk(b,'b','',du(t.ar[L.length-1]-t.dp[0]));mk(b,'small','',tr<2?'direct':tr-1+' change'+(tr>2?'s':''));
    b.onclick=function(){S=j;draw()}});s.style.display=D.i.length>1?'':'none'}
function stop(h,tm,dl,nm,sub,pl){var r=mk(h,'div','st'),a=mk(r,'div','tm',tm),g=mk(r,'div','rl'),b=mk(r,'div','nm',nm);
  if(dl>0)mk(a,'span','chip '+sv(dl),'+'+dl);mk(g,'i');if(pl)mk(b,'span','pl','Pl. '+pl);if(sub)mk(b,'small','',sub)}
function tl(){var h=$('tl'),L=D.i[S]||[];h.textContent='';if(!L.length){mk(h,'div','em','No connection found');return}
  var t=T(L);stop(h,L[0][2],+L[0][3],D.o,'',L[0][0]=='Walk'?'':L[0][6]);
  L.forEach(function(l,i){var r=mk(h,'div','lg');mk(r,'div','tm');var g=mk(r,'div','rl');mk(g,'s');var b=mk(r,'div','nm');
    mk(b,'span','bd '+bc(l[0]),l[0]);b.appendChild(document.createTextNode(du(t.ar[i]-t.dp[i])+(l[7]?' \u00b7 cancelled':'')));
    var nx=L[i+1];stop(h,l[4],+l[5],l[1],nx?'change \u00b7 departs '+nx[2]+(+nx[3]?' (+'+nx[3]+')':''):'',nx&&nx[0]!='Walk'?nx[6]:'')})}
function draw(){try{hero();strip();tl()}catch(e){$('tl').textContent='Display error'}}
function load(raw){try{var x=JSON.parse(raw||'{}');D={o:x.o,d:x.d,t:x.t||'00:00',i:Array.isArray(x.i)?x.i.filter(function(l){return Array.isArray(l)&&l.length}):[]};S=0;t0=Date.now();draw();return 1}
  catch(e){$('tl').textContent='No data. Send /trip again.'}}
function note(t){$('f').textContent=t}
if(W){
  document.documentElement.className=W.colorScheme=='dark'?'dark':'';
  load(W.chatData);setInterval(hero,15000);
  try{W.onEvent('chatDataChanged',function(){load(W.chatData)})}catch(e){}
  if(W.ready)try{W.ready()}catch(e){}
  var act=function(c,msg){return function(){
    if(busy)return;busy=1;var bs=document.querySelectorAll('button');bs.forEach(function(b){b.disabled=true});note(msg);
    var done=function(m){busy=0;bs.forEach(function(b){b.disabled=false});note(m)},
    to=setTimeout(function(){done('Timed out. Try again.')},15000);
    try{W.request(c).then(function(a){clearTimeout(to);if(!busy)return;
      if(a&&a.result&&load(a.result))done('Updated '+D.t+' \u00b7 Data: Transitous');else done('Nothing new')},
      function(e){clearTimeout(to);done('Failed ('+(e&&e.code||'error')+')')})}
    catch(e){clearTimeout(to);done('Failed')}}};
  $('rf').onclick=act('r','Refreshing...');$('nx').onclick=act('n','Loading later trips...');$('sw').onclick=act('s','Swapping...');
}else{load('{}');$('rf').style.display=$('nx').style.display=$('sw').style.display='none';note('Open this in Telegram')}
</script>"""


def encode_trip(
    origin: str, destination: str, journeys: list[Journey], now: datetime | None = None
) -> str:
    """Compact JSON for the trip widget.

    {"o": origin, "d": destination, "t": "HH:MM" (bot clock), "i": [itinerary, ...]}
    itinerary = list of legs; leg = [line, to, planned dep, dep delay, planned arr,
    arr delay, platform, cancelled 0/1]. Walking legs have line "Walk".
    Alternatives and name lengths are reduced until the payload fits in 1024 bytes.
    """
    now = now or datetime.now(BERLIN)

    def short(name: str, n: int) -> str:
        return name if len(name) <= n else name[: n - 1].rstrip() + "…"

    def build(name_len: int) -> list[list[list]]:
        its = []
        for j in journeys:
            legs = [l for l in j.legs if l.departure and l.arrival]
            if not any(l.line != "walk" for l in legs):
                continue
            enc = []
            for idx, l in enumerate(legs):
                dd, ad = max(l.departure_delay_min, 0), max(l.arrival_delay_min, 0)
                to = destination if idx == len(legs) - 1 and l.destination in ("END", "?") else l.destination
                enc.append([
                    "Walk" if l.line == "walk" else l.line[:9],
                    short(to, name_len),
                    (l.departure - timedelta(minutes=dd)).strftime("%H:%M"),
                    dd,
                    (l.arrival - timedelta(minutes=ad)).strftime("%H:%M"),
                    ad,
                    "" if l.line == "walk" else (l.platform or "")[:5],
                    int(l.cancelled),
                ])
            its.append(enc)
        return its

    text = ""
    for name_len in (18, 13, 9):
        its = build(name_len)
        while True:
            payload = {"o": short(origin, 26), "d": short(destination, 26), "t": now.strftime("%H:%M"), "i": its}
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(text.encode()) <= MAX_DATA_BYTES or len(its) <= 1:
                break
            its = its[:-1]
        if len(text.encode()) <= MAX_DATA_BYTES:
            return text
    return text  # extremely long trips: the sender still shows the best effort


@dataclass(frozen=True)
class WidgetState:
    kind: str  # "board" or "trip"
    a_id: str  # station id, or trip origin (station id or "lat,lon")
    a_name: str
    b_id: str = ""
    b_name: str = ""
    after: str = ""  # ISO-8601 UTC time to search from ("" = now), trips only
    seen: str = ""  # ISO-8601 UTC departure of the last connection shown (for "Later")


class WidgetStore:
    """Remembers what each sent widget shows, so refresh queries work after a restart."""

    def __init__(self, path: str | Path = "widgets.sqlite3"):
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS widget_state (chat_id INTEGER, message_id INTEGER, "
            "kind TEXT, a_id TEXT, a_name TEXT, b_id TEXT, b_name TEXT, after TEXT, seen TEXT, "
            "PRIMARY KEY (chat_id, message_id))"
        )

    def save(self, chat_id: int, message_id: int, state: WidgetState) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO widget_state VALUES (?,?,?,?,?,?,?,?,?)",
                (chat_id, message_id, state.kind, state.a_id, state.a_name,
                 state.b_id, state.b_name, state.after, state.seen),
            )

    def get(self, chat_id: int, message_id: int) -> WidgetState | None:
        row = self._db.execute(
            "SELECT kind, a_id, a_name, b_id, b_name, after, seen FROM widget_state "
            "WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()
        return WidgetState(*row) if row else None
