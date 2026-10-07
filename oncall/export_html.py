"""Renders the database rows as a self-contained dashboard page."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

KIND_GROUP = {
    "lost_edit": "down", "downgrade": "down", "canceled": "down",
    "upgrade": "up", "payment_issue": "warn", "trial": "warn",
    "changed": "info", "unknown_plan": "info", "no_data": "info", "same": "",
}
CATEGORY_LABEL = {"profile_quality": "Profile quality", "color_rendering": "Colour rendering", "masking": "Masking",
                  "straightening": "Straightening", "cropping": "Cropping", "others": "Others"}


def _plain(v):
    return v.isoformat(sep=" ", timespec="minutes") if isinstance(v, (datetime, date)) else v


def to_view(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        r = {k: _plain(v) for k, v in r.items()}
        r["group"] = KIND_GROUP.get(r.get("change_kind") or "", "")
        if r.get("data_gap"):
            r["group"] = r["group"] or "info"
        r["category_label"] = CATEGORY_LABEL.get(r.get("category") or "", "")
        out.append(r)
    return out


def write_page(rows: list[dict], path: str):
    html = TEMPLATE.replace("__DATA__", json.dumps(to_view(rows)).replace("</", "<\\/"))
    html = html.replace("__UPDATED__", datetime.now(timezone.utc).replace(tzinfo=None).strftime("%-d %b %Y, %H:%M UTC"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html)


TEMPLATE = r'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>AI-quality on-calls: plan at ticket vs. now</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#EDF0F2;--surface:#FFFFFF;--ink:#17202B;--muted:#5E6977;--rule:#D5DBE1;--down:#B23A2E;--up:#2E7A4E;--warn:#9A6210;--info:#3D5A80;--hover:#F4F6F8;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11161C;--surface:#182029;--ink:#E6EAEE;--muted:#98A3B0;--rule:#2B3540;--down:#F07A6E;--up:#6CC490;--warn:#E3A84A;--info:#8EB0DA;--hover:#1E2832}}
:root[data-theme="dark"]{--bg:#11161C;--surface:#182029;--ink:#E6EAEE;--muted:#98A3B0;--rule:#2B3540;--down:#F07A6E;--up:#6CC490;--warn:#E3A84A;--info:#8EB0DA;--hover:#1E2832}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Public Sans",system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px;line-height:1.5;font-variant-numeric:tabular-nums}
.wrap{max-width:1500px;margin:0 auto;padding:2rem 1.25rem 3rem}
h1{font-size:1.75rem;line-height:1.2;font-weight:700;margin:0 0 .4rem;letter-spacing:-.01em}
.lede{color:var(--muted);max-width:75ch;margin:0 0 1.5rem}
.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem;align-items:center}
.filters button,.filters select{font:inherit;font-size:.9rem;border:1px solid var(--rule);background:var(--surface);color:var(--ink);padding:.45rem .8rem;border-radius:6px;cursor:pointer}
.filters button{display:flex;gap:.5rem;align-items:baseline}
.filters button b{font-weight:700}
.filters button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
:focus-visible{outline:2px solid var(--info);outline-offset:2px}
.search{margin-left:auto;font:inherit;font-size:.9rem;padding:.45rem .7rem;border:1px solid var(--rule);border-radius:6px;background:var(--surface);color:var(--ink);min-width:220px}
.tablebox{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);border-radius:8px}
table{border-collapse:collapse;width:100%;min-width:1440px}
th{position:sticky;top:0;background:var(--surface);text-align:left;font-size:.8rem;font-weight:600;color:var(--muted);border-bottom:1px solid var(--rule);padding:0}
th button{all:unset;display:block;padding:.65rem .75rem;cursor:pointer;width:100%;box-sizing:border-box}
th button[data-dir="asc"]::after{content:" \2191"}th button[data-dir="desc"]::after{content:" \2193"}
td{padding:.65rem .75rem;border-bottom:1px solid var(--rule);vertical-align:top;font-size:.875rem}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--hover)}
tr td:first-child{box-shadow:inset 4px 0 0 var(--k,transparent)}
tr[data-g="down"]{--k:var(--down)}tr[data-g="up"]{--k:var(--up)}tr[data-g="warn"]{--k:var(--warn)}tr[data-g="info"]{--k:var(--info)}
a{color:var(--info);text-decoration:none}a:hover{text-decoration:underline}
.key{font-weight:600;white-space:nowrap}
.sub{color:var(--muted);font-size:.78rem;word-break:break-all}
.cat{display:inline-block;font-size:.75rem;font-weight:600;border:1px solid var(--rule);border-radius:4px;padding:0 .35rem;margin-bottom:.2rem}
.issue{max-width:38ch}
.plan{white-space:nowrap}
.muted{color:var(--muted)}
.note{max-width:30ch;font-size:.82rem}
.note[data-g="down"]{color:var(--down);font-weight:600}.note[data-g="up"]{color:var(--up);font-weight:600}
.note[data-g="warn"]{color:var(--warn)}.note[data-g="info"]{color:var(--info)}
.flag{display:block;color:var(--warn);font-size:.78rem;margin-top:.2rem}
.empty{padding:2rem;text-align:center;color:var(--muted)}
footer{color:var(--muted);font-size:.82rem;margin-top:1.25rem;max-width:95ch}
</style></head><body><div class="wrap">
<h1>AI-quality on-calls: plan at ticket vs. now</h1>
<p class="lede">Editing pod tickets tagged editing-ai-quality. Plan at ticket is the user's plan on their last PostHog event before the ticket was created; plan now is refreshed daily. Last updated __UPDATED__.</p>
<div class="filters" role="group" aria-label="Filter tickets">
<button data-f="all" aria-pressed="true">All <b id="c-all"></b></button>
<button data-f="down" aria-pressed="false">Downgraded or lost <b id="c-down"></b></button>
<button data-f="warn" aria-pressed="false">Trial or payment issue <b id="c-warn"></b></button>
<button data-f="info" aria-pressed="false">Data gaps <b id="c-info"></b></button>
<select id="cat" aria-label="Issue category"><option value="">All categories</option></select>
<input class="search" type="search" placeholder="Search ticket, email, assignee, issue" aria-label="Search">
</div>
<div class="tablebox"><table><thead><tr>
<th><button data-s="ticket_key">Ticket</button></th>
<th><button data-s="created_at" data-dir="desc">Created</button></th>
<th><button data-s="category">Feature &amp; issue</button></th>
<th><button data-s="email">User</button></th>
<th><button data-s="assignee">Assignee</button></th>
<th><button data-s="jira_status">Jira status</button></th>
<th><button data-s="profile_type">Profile type</button></th>
<th><button data-s="profile_name">Profile name &amp; ID</button></th>
<th><button data-s="plan_at_ticket">Plan at ticket</button></th>
<th><button data-s="plan_now">Plan now</button></th>
<th><button data-s="change_kind">What changed</button></th>
</tr></thead><tbody id="rows"></tbody></table></div>
<footer>Sources: Jira (project ONCL, Pod = Editing, Issue topic = editing-ai-quality), Intercom conversation linked on the ticket, PostHog person and event properties. Feature and summary are generated from the Intercom chat. Profile comes from an ID on the ticket, else a profile the ticket names among those the user recently edited with, else the user's last edit before the ticket. Plan names are matched through the mapping in config.yaml.</footer>
</div>
<script>
const DATA = __DATA__;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const dash='<span class="muted">—</span>';
const plan=(p,s,c)=>p||s?`${esc(p||'(blank)')}<div class="sub">${esc([s,c].filter(Boolean).join(', '))}</div>`:dash;
let filter='all',cat='',q='',sortKey='created_at',dir='desc';
for(const g of ['down','warn','info'])document.getElementById('c-'+g).textContent=DATA.filter(r=>r.group===g).length;
document.getElementById('c-all').textContent=DATA.length;
const sel=document.getElementById('cat');
[...new Set(DATA.map(r=>r.category_label).filter(Boolean))].sort().forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;sel.append(o);});
function render(){
  let rows=DATA.filter(r=>(filter==='all'||r.group===filter)&&(!cat||r.category_label===cat)&&
    (!q||[r.ticket_key,r.email,r.user_id,r.assignee,r.summary,r.issue_summary,r.profile_name,r.profile_id].join(' ').toLowerCase().includes(q)));
  rows.sort((a,b)=>{const x=String(a[sortKey]??''),y=String(b[sortKey]??'');return (x<y?-1:x>y?1:0)*(dir==='asc'?1:-1);});
  const tb=document.getElementById('rows');
  if(!rows.length){tb.innerHTML='<tr><td colspan="11" class="empty">No tickets match. Clear the search or pick another filter.</td></tr>';return;}
  tb.innerHTML=rows.map(r=>`<tr data-g="${r.group}">
   <td><a class="key" href="https://aftershoot.atlassian.net/browse/${esc(r.ticket_key)}" target="_blank" rel="noopener">${esc(r.ticket_key)}</a>${r.intercom_url?`<div class="sub"><a href="${esc(r.intercom_url)}" target="_blank" rel="noopener">Intercom</a></div>`:'<div class="sub">No Intercom link</div>'}</td>
   <td>${esc((r.created_at||'').slice(0,10))}</td>
   <td class="issue">${r.category_label?`<span class="cat">${esc(r.category_label)}</span><br>`:''}${esc(r.issue_summary||r.summary)}${r.plan_mismatch?`<span class="flag">${esc(r.plan_mismatch)}</span>`:''}</td>
   <td>${esc(r.email)||dash}<div class="sub">${esc(r.user_id)}</div></td>
   <td>${esc(r.assignee)||dash}</td>
   <td>${esc(r.jira_status)}</td>
   <td>${r.profile_type?esc(r.profile_type[0].toUpperCase()+r.profile_type.slice(1)):dash}</td>
   <td>${r.profile_id?`${esc(r.profile_name||'(name not found)')}<div class="sub">${esc(r.profile_id)}</div><div class="sub">${({ticket:'ID on ticket',named:'Named in ticket',last_edit:'Last edit before ticket'})[r.profile_source]||''}</div>`:dash}</td>
   <td class="plan">${plan(r.plan_at_ticket,r.status_at_ticket,r.cycle_at_ticket)}</td>
   <td class="plan">${plan(r.plan_now,r.status_now,r.cycle_now)}</td>
   <td class="note" data-g="${r.group}">${esc(r.change_note)||'<span class="muted">No change</span>'}${r.data_gap?`<span class="flag">${esc(r.data_gap)}</span>`:''}</td></tr>`).join('');
}
document.querySelectorAll('.filters button').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.f;document.querySelectorAll('.filters button').forEach(x=>x.setAttribute('aria-pressed',x===b));render();}));
sel.addEventListener('change',()=>{cat=sel.value;render();});
document.querySelector('.search').addEventListener('input',e=>{q=e.target.value.trim().toLowerCase();render();});
document.querySelectorAll('th button').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.s;dir=(sortKey===k&&dir==='asc')?'desc':'asc';sortKey=k;document.querySelectorAll('th button').forEach(x=>x.removeAttribute('data-dir'));b.dataset.dir=dir;render();}));
render();
</script></body></html>'''
