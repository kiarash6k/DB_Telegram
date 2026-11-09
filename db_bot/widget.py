"""Departure-board widget (Telegram Bot API 10.4).

The widget is static HTML with no network access. The bot passes data in as JSON
(``chat_data`` when sending, and as the answer to a refresh query). Both are
limited to 1024 bytes, so the payload is kept compact.
"""
from __future__ import annotations

import json
import sqlite3
import zlib
from datetime import datetime
from pathlib import Path

from .api import BERLIN, Departure

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


def html_fits() -> bool:
    return len(zlib.compress(WIDGET_HTML.encode(), 9)) <= MAX_HTML_COMPRESSED


class WidgetStore:
    """Remembers which station each sent widget shows, so refresh queries work after a restart."""

    def __init__(self, path: str | Path = "widgets.sqlite3"):
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS widgets (chat_id INTEGER, message_id INTEGER, "
            "station_id TEXT, station_name TEXT, PRIMARY KEY (chat_id, message_id))"
        )

    def save(self, chat_id: int, message_id: int, station_id: str, station_name: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO widgets VALUES (?,?,?,?)",
                (chat_id, message_id, station_id, station_name),
            )

    def get(self, chat_id: int, message_id: int) -> tuple[str, str] | None:
        row = self._db.execute(
            "SELECT station_id, station_name FROM widgets WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        ).fetchone()
        return (row[0], row[1]) if row else None
