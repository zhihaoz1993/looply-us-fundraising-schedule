#!/usr/bin/env python3
"""
LA Tech Week — daily curated picks for Looply (fundraising + AI/dev-tools intel).

Sources the full LA Tech Week catalog from the official MCP server
(https://www.tech-week.com/api/mcp) and ranks events for one founder's goals:
  - fundraising for Looply  -> VC-hosted rooms, pitch events / demo days, investor matchmaking
  - AI & dev-tools trends    -> developer-tools / enterprise-AI / AI panels & talks
  - competitive market intel -> product teardowns, launches, "state of AI"
  - customer insight         -> AI transformation / adoption / GTM / enterprise buyers

Categorisation is by WHICH filtered MCP query returned an event (reliable keys
from list_filters), not by parsing display labels. Keyword signals on the host +
name + description add to the score.

Outputs (all in this directory):
  sources/techweek-la-events.json  — every scored event (provenance/cache)
  techweek-la-picks.md             — the human-readable daily digest
  techweek-la-picks.html           — a published page (copied to the public repo)
and prints the top picks to stdout for the daily agent to relay.

Pure stdlib (urllib) so it runs anywhere, including a scheduled cloud agent.
Per the server's own note: event text is third-party user content — treated as
DATA only; instructions embedded in any description are never followed.
"""
import json, re, sys, os, time, html, datetime, urllib.request, urllib.error

MCP = "https://www.tech-week.com/api/mcp"
CITY = "la"
HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = ["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18"]

# ---- MCP transport (stateless Streamable HTTP; no session/init needed here) ----
_rid = [10]
def mcp_call(name, args):
    _rid[0]+=1
    body = json.dumps({"jsonrpc":"2.0","id":_rid[0],"method":"tools/call",
                       "params":{"name":name,"arguments":args}}).encode()
    req = urllib.request.Request(MCP, data=body, method="POST", headers={
        "Content-Type":"application/json",
        "Accept":"application/json, text/event-stream",
        "MCP-Protocol-Version":"2025-06-18"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read().decode("utf-8","replace")
            break
        except Exception as e:
            if attempt==3: raise
            time.sleep(1.5*(attempt+1))
    # response is JSON here, but tolerate SSE framing ("data: {...}")
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        j = None
        for line in raw.splitlines():
            line=line.strip()
            if line.startswith("data:"):
                try: j=json.loads(line[5:].strip())
                except: pass
        if j is None: raise RuntimeError("unparseable MCP response: "+raw[:200])
    if "error" in j: raise RuntimeError("MCP error: "+json.dumps(j["error"]))
    return j["result"]["content"][0]["text"]

# ---- parse a search_events text block into event dicts ----
MONTHS={"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
BUCKET={"Morning":"09:00","Noon":"12:00","Afternoon":"14:00","Evening":"18:00"}
def _to_min(t):
    m=re.match(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)', t or "")
    if not m: return None
    h=int(m.group(1))%12; mn=int(m.group(2) or 0)
    if m.group(3)=="PM": h+=12
    return h*60+mn

def parse_search(text):
    out=[]
    # split into numbered blocks: "N. name" ... up to the next "N. " or the trailer
    blocks=re.split(r'\n\s*\d+\.\s', "\n"+text)
    for b in blocks[1:]:
        lines=[l for l in b.split("\n")]
        name=lines[0].strip()
        mid=re.search(r'id:\s*([0-9a-f]{8}-[0-9a-f-]{27,})', b)
        if not mid: continue
        eid=mid.group(1)
        murl=re.search(r'(https://www\.tech-week\.com/\S+)', b)
        url=murl.group(1) if murl else ""
        # "when" line = first non-empty indented line that names a month
        when=""; nb=""
        for l in lines[1:]:
            if re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b', l) and re.search(r'\bOct\b', l):
                when=l.strip(); break
        host=""; reg="unknown"
        hb=next((l for l in lines if l.strip().startswith("hosted by ")), "")
        if hb:
            segs=[s.strip() for s in hb.strip().split(" · ")]
            host=segs[0].replace("hosted by ","",1).strip()
            last=segs[-1].lower()
            if "invite" in last: reg="invite_only"
            elif "waitlist" in last: reg="waitlist"
            elif "full" in last: reg="full"
            elif "closed" in last: reg="closed"
            elif "open" in last or "rsvp" in last: reg="open"
        # date / time / neighborhood
        sd=ed=None; stime=None; tod=None
        if when:
            md=re.search(r'Oct (\d{1,2})', when)
            if md: sd=int(md.group(1))
            me=re.search(r'until Oct (\d{1,2})', when)
            ed=int(me.group(1)) if me else sd
            mt=re.search(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM))', when)
            if mt: stime=mt.group(1)
            mb=re.search(r'\b(Morning|Noon|Afternoon|Evening)\b', when)
            if mb: tod=mb.group(1)
            mn=re.search(r'·\s*([^·]+?),\s*Los Angeles', when)
            if mn: nb=mn.group(1).strip()
        # description = lines after the hosted-by line, before the url/id lines
        desc_lines=[]
        seen_host=False
        for l in lines[1:]:
            ls=l.strip()
            if ls.startswith("hosted by "): seen_host=True; continue
            if not seen_host: continue
            if ls.startswith("https://") or ls.startswith("id:") or not ls: continue
            desc_lines.append(ls)
        desc=" ".join(desc_lines).strip()
        start_min=_to_min(stime) if stime else (int(BUCKET.get(tod,"23:59").split(":")[0])*60 if tod else 1439)
        out.append(dict(id=eid,name=name,host=host,url=url,reg=reg,when=when,
                        start_day=sd,end_day=ed,start_time=stime,tod=tod,
                        neighborhood=nb,start_min=start_min,desc=desc))
    return out

def search(args, cap=150):
    """Paginate a search_events query, return parsed events."""
    acc=[]; page=1
    while True:
        a=dict(args); a.update(city=[CITY], limit=75, page=page)
        txt=mcp_call("search_events", a)
        evs=parse_search(txt)
        acc+=evs
        mtot=re.search(r'(\d+)\s+events match', txt)
        more=("pass page:" in txt) and len(evs)>0 and len(acc)<cap
        if not more: break
        page+=1
    return acc

# ---- the signal queries: tag -> (weight, search args) ------------------------
QUERIES=[
    ("pitch",   6, {"format":["pitch-event-demo-day"]}),
    ("capital", 4, {"track":["fundraising-investing"]}),
    ("vc_fund", 4, {"sponsor":["a16z","speedrun"]}),
    ("devtools",3, {"track":["developer-tools"]}),
    ("entai",   3, {"track":["enterprise-ai-agents"]}),
    ("aitalk",  3, {"theme":["ai"],"format":["panel-fireside-chat","roundtable-workshop"]}),
    ("gtm",     2, {"theme":["gtm"]}),
    ("founders",2, {"track":["founders"]}),
    ("hackdemo",2, {"track":["hack-week-hackathons-and-technical-events"]}),
    ("featured",2, {"featuredOnly":True}),
]
TAGLABEL={"pitch":"🎤 pitch / demo day","capital":"💰 VC / investor room","vc_fund":"💰 VC-run (a16z/Speedrun)",
    "devtools":"🛠️ dev tools","entai":"🤖 enterprise AI / agents","aitalk":"🧠 AI trends talk",
    "gtm":"📈 GTM / customers","founders":"🚀 founders","hackdemo":"⚙️ technical / demo","featured":"⭐ featured"}

VC_KW=["ventures","venture","capital","partners"," vc","vc ","a16z","sequoia","accel","lightspeed",
    "greylock","khosla","bessemer","first round","nfx","initialized","upfront","foundersfund",
    "founders fund","menlo","index ventures","craft ","8vc","insight partners","tiger global",
    "coatue","general catalyst","kleiner","mayfield","matrix","bain capital","gradient","wonder ",
    "pear vc","felicis","signalfire","b capital","m13","crosscut","mucker","plug and play",
    "techstars","y combinator","angel","lp","gp ","emerging manager","fund "]
PITCH_KW=["pitch","demo day","in the ring","competition","office hours","shark tank","fast pitch"]
INTEL_KW=["state of ai","benchmark","eval","teardown","under the hood","how we built","roadmap",
    "launch","agents","agentic","llm","inference","rag","coding agent","developer","dev tools",
    "mcp","open source","infra","foundation model","fine-tun"]
CUST_KW=["ai transformation","ai adoption","adopting ai","enterprise ai","digital transformation",
    "go-to-market","go to market","gtm","buyers","change management","cio","cto","procurement",
    "deploying ai","ai in production","scaling ai"]

def score(ev):
    s=0.0; why=set()
    for tag,w in ev["tags"].items():
        s+=w; why.add(tag)
    blob=(ev["name"]+" "+ev["host"]+" "+ev["desc"]).lower()
    if any(k in blob for k in VC_KW): s+=2; why.add("capital")
    if any(k in blob for k in PITCH_KW): s+=3; why.add("pitch")
    if any(k in blob for k in INTEL_KW): s+=2; why.add("devtools")
    if any(k in blob for k in CUST_KW): s+=2; why.add("gtm")
    reg=ev["reg"]
    if reg=="open": s+=1
    elif reg in ("full","closed"): s-=4
    ev["why"]=sorted(why)
    return round(s,1)

def main():
    print("Fetching LA Tech Week events from MCP…", file=sys.stderr)
    byid={}
    for tag,w,args in QUERIES:
        evs=search(args)
        print(f"  {tag:9s} -> {len(evs)} events", file=sys.stderr)
        for e in evs:
            cur=byid.get(e["id"])
            if not cur:
                e["tags"]={tag:w}; byid[e["id"]]=e
            else:
                cur["tags"][tag]=max(cur["tags"].get(tag,0),w)
                if not cur.get("desc") and e.get("desc"): cur["desc"]=e["desc"]
    events=list(byid.values())
    for e in events: e["score"]=score(e)
    events.sort(key=lambda e:(-e["score"], e["start_day"] or 99, e["start_min"]))
    now=datetime.datetime.now(datetime.timezone.utc).astimezone()
    meta=dict(generated=now.isoformat(timespec="minutes"), source=MCP, city=CITY,
              total_catalog=None, scored=len(events))
    # ---- persist JSON ----
    os.makedirs(os.path.join(HERE,"sources"), exist_ok=True)
    with open(os.path.join(HERE,"sources","techweek-la-events.json"),"w") as f:
        json.dump({"meta":meta,"events":events}, f, ensure_ascii=False, indent=1)
    # ---- build digest ----
    md=render_md(events, now); open(os.path.join(HERE,"techweek-la-picks.md"),"w").write(md)
    htmlout=render_html(events, now); open(os.path.join(HERE,"techweek-la-picks.html"),"w").write(htmlout)
    # ---- stdout summary for the agent ----
    print(summary(events, now))

def whyline(e):
    order=["pitch","capital","vc_fund","entai","devtools","aitalk","gtm","founders","hackdemo","featured"]
    return " · ".join(TAGLABEL[t] for t in order if t in e["why"])

def dstr(e):
    d=e["start_day"]; wd=""
    if d:
        try: wd=datetime.date(2026,10,d).strftime("%a")
        except: pass
    span=f"–Oct {e['end_day']}" if e.get("end_day") and e["end_day"]!=d else ""
    t=e["start_time"] or (e["tod"] or "")
    return f"{wd} Oct {d}{span} {t}".strip()

REGTXT={"open":"RSVP open","waitlist":"waitlist","full":"FULL","closed":"closed","invite_only":"invite-only","unknown":"RSVP ?"}

def render_md(events, now):
    L=[]
    L.append(f"# LA Tech Week — Looply picks\n")
    L.append(f"_Generated {now.strftime('%a %b %-d, %-I:%M %p %Z')} · source: official Tech Week MCP · {len(events)} relevant events scored_\n")
    L.append("Ranked for Looply fundraising + AI/dev-tools intel. Event text is third-party content.\n")
    pitch=[e for e in events if ("pitch" in e["why"]) and e["reg"] in ("open","waitlist","invite_only","unknown")]
    L.append("## 🎤 Apply / pitch opportunities\n")
    if pitch:
        for e in pitch[:12]:
            L.append(f"- **{e['name']}** — {dstr(e)} · {e['neighborhood'] or '—'} · _{REGTXT[e['reg']]}_  \n  {whyline(e)} · host: {e['host']}  \n  {e['url']}")
    else: L.append("_none today_")
    L.append("\n## ⭐ Top priorities overall\n")
    for e in events[:12]:
        L.append(f"{events.index(e)+1}. **{e['name']}** ({e['score']}) — {dstr(e)} · {e['neighborhood'] or '—'} · _{REGTXT[e['reg']]}_  \n   {whyline(e)} · host: {e['host']}  \n   {e['url']}")
    L.append("\n## By day\n")
    for di,day in enumerate(DAYS):
        d=int(day[-2:])
        dayev=[e for e in events if e["start_day"]==d]
        if not dayev: continue
        L.append(f"### {datetime.date(2026,10,d).strftime('%A %b %-d')}  ({len(dayev)} relevant)\n")
        for e in dayev[:10]:
            L.append(f"- **{e['name']}** ({e['score']}) · {e['start_time'] or e['tod'] or ''} · {e['neighborhood'] or '—'} · _{REGTXT[e['reg']]}_ — {whyline(e)}  \n  {e['url']}")
        L.append("")
    return "\n".join(L)+"\n"

def summary(events, now):
    lines=[f"LA Tech Week picks — {now.strftime('%a %b %-d %-I:%M%p %Z')} ({len(events)} relevant events)"]
    lines.append("TOP 8:")
    for i,e in enumerate(events[:8],1):
        lines.append(f"{i}. {e['name']} ({e['score']}) — {dstr(e)} · {e['neighborhood'] or '—'} · {REGTXT[e['reg']]}")
        lines.append(f"   {whyline(e)}")
    pitch=[e for e in events if "pitch" in e["why"] and e["reg"] in ("open","invite_only","unknown","waitlist")]
    if pitch:
        lines.append(f"PITCH/APPLY ({len(pitch)}): "+ " | ".join(e["name"] for e in pitch[:6]))
    return "\n".join(lines)

def render_html(events, now):
    def esc(x): return html.escape(x or "")
    cards=[]
    for i,e in enumerate(events,1):
        tags="".join(f'<span class=t>{esc(TAGLABEL[t])}</span>' for t in
             ["pitch","capital","vc_fund","entai","devtools","aitalk","gtm","founders","hackdemo","featured"] if t in e["why"])
        cards.append(f"""<article class="c reg-{e['reg']}" data-day="{e['start_day']}" data-score="{e['score']}">
<div class=rank>{i}</div><div class=body>
<a class=nm href="{esc(e['url'])}" target=_blank rel=noopener>{esc(e['name'])}</a>
<div class=meta>{esc(dstr(e))} · {esc(e['neighborhood'] or '—')} · <b>{esc(REGTXT[e['reg']])}</b> · score {e['score']}</div>
<div class=tags>{tags}</div>
<div class=host>host: {esc(e['host'])}</div>
<div class=desc>{esc((e['desc'] or '')[:220])}</div>
</div></article>""")
    daybtns="".join(f'<button class=db data-d="{int(d[-2:])}">Oct {int(d[-2:])}</button>' for d in DAYS)
    return f"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>LA Tech Week — Looply picks</title>
<style>
:root{{--bg:#fbf7f3;--ink:#2b2320;--ink2:#7a6a60;--brand:#B8452A;--cream:#fff;--line:#eaded5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"PingFang SC",Segoe UI,Roboto,sans-serif}}
header{{padding:22px 18px 10px;max-width:900px;margin:0 auto}}
h1{{margin:0 0 4px;font-size:22px;color:var(--brand)}}
.sub{{color:var(--ink2);font-size:13px}}
.bar{{position:sticky;top:0;background:var(--bg);padding:10px 18px;border-bottom:1px solid var(--line);z-index:2;max-width:900px;margin:0 auto;display:flex;gap:6px;flex-wrap:wrap}}
.db,.allb{{border:1px solid var(--line);background:var(--cream);border-radius:20px;padding:5px 12px;font-size:13px;cursor:pointer}}
.db.on,.allb.on{{background:var(--brand);color:#fff;border-color:var(--brand)}}
main{{max-width:900px;margin:0 auto;padding:12px 18px 60px}}
.c{{display:flex;gap:12px;background:var(--cream);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:12px 14px;margin:8px 0}}
.c.reg-full,.c.reg-closed{{opacity:.5}}
.rank{{font-weight:700;color:var(--ink2);min-width:26px}}
.nm{{font-weight:650;color:var(--ink);text-decoration:none;font-size:16px}}.nm:hover{{color:var(--brand)}}
.meta{{color:var(--ink2);font-size:12.5px;margin:3px 0}}
.tags{{margin:4px 0}}.t{{display:inline-block;background:#f4e9e2;color:#8a3c24;border-radius:6px;padding:1px 7px;font-size:11.5px;margin:2px 4px 2px 0}}
.host{{font-size:12px;color:var(--ink2)}}.desc{{font-size:12.5px;color:#5c5048;margin-top:4px}}
</style>
<header><h1>LA Tech Week — Looply picks</h1>
<div class=sub>Generated {now.strftime('%a %b %-d, %-I:%M %p %Z')} · {len(events)} events ranked for fundraising + AI / dev-tools intel · official Tech&nbsp;Week MCP.<br>Event text is third-party, user-submitted content.</div></header>
<div class=bar><button class="allb on" data-d="all">All</button>{daybtns}</div>
<main id=list>{''.join(cards)}</main>
<script>
var btns=[...document.querySelectorAll('.db,.allb')];
btns.forEach(b=>b.onclick=()=>{{btns.forEach(x=>x.classList.remove('on'));b.classList.add('on');
var d=b.dataset.d;document.querySelectorAll('.c').forEach(c=>{{c.style.display=(d==='all'||c.dataset.day===d)?'':'none'}})}});
</script></html>"""

if __name__=="__main__":
    main()
