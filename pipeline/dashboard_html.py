# -*- coding: utf-8 -*-
"""Interface data-warehouse multi-pages du pipeline Dakar (servie sur 9090 par metrics.py).
App vanilla autonome (pas de CDN) : routing par hash + kit de graphes SVG maison."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dakar · Data Warehouse Pipeline</title>
<style>
  :root{ --bg:#070d1a; --bg2:#0b1426; --card:#111d33; --card2:#0e1830; --bd:#1d2c47;
         --txt:#e8eef7; --mut:#7d8ca6; --acc:#38bdf8; --acc2:#818cf8;
         --ok:#22c55e; --warn:#eab308; --crit:#ef4444; }
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:radial-gradient(1200px 600px at 80% -10%,#13203a 0%,var(--bg) 55%); color:var(--txt);
       display:flex; min-height:100vh}
  /* Sidebar */
  .side{width:230px; flex:none; background:linear-gradient(180deg,#0c1730,#0a1124);
        border-right:1px solid var(--bd); padding:1.2rem .8rem; position:sticky; top:0; height:100vh; overflow:auto}
  .brand{display:flex; align-items:center; gap:.6rem; font-weight:800; font-size:1.05rem; padding:.2rem .6rem 1rem}
  .brand .logo{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,var(--acc),var(--acc2));
        display:grid;place-items:center;font-size:1rem}
  .nav a{display:flex; align-items:center; gap:.7rem; padding:.65rem .8rem; border-radius:.7rem;
        color:var(--mut); text-decoration:none; font-size:.9rem; font-weight:600; margin-bottom:.2rem; transition:.15s}
  .nav a:hover{background:#13203c; color:var(--txt)}
  .nav a.active{background:#15244180; color:#fff; box-shadow:inset 3px 0 0 var(--acc)}
  .nav .ic{font-size:1.05rem; width:1.3rem; text-align:center}
  .side .foot{position:sticky; bottom:0; padding-top:1rem; font-size:.7rem; color:#4d5d77}
  /* Main */
  .main{flex:1; padding:1.6rem 2rem; max-width:1500px}
  .top{display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem; margin-bottom:.4rem}
  h1{font-size:1.35rem; margin:0; display:flex; align-items:center; gap:.6rem}
  .pulse{width:11px;height:11px;border-radius:50%;background:var(--ok);animation:p 2s infinite}
  @keyframes p{0%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}70%{box-shadow:0 0 0 9px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
  .sub{color:var(--mut);font-size:.8rem}
  .lead{color:var(--mut); font-size:.9rem; margin:.1rem 0 1.4rem}
  h2{font-size:.78rem;color:var(--acc);text-transform:uppercase;letter-spacing:.07em;margin:1.8rem 0 .8rem}
  .grid{display:grid;gap:1rem}
  .kpis{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
  .cards{grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
  .two{grid-template-columns:1fr 1fr} @media(max-width:1000px){.two{grid-template-columns:1fr} .side{width:64px} .brand span,.nav a span.lbl{display:none}}
  .card{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--bd);
        border-radius:1rem;padding:1.15rem; position:relative; overflow:hidden}
  .card .v{font-size:1.8rem;font-weight:800}
  .card .l{font-size:.72rem;color:var(--mut);margin-top:.3rem;text-transform:uppercase;letter-spacing:.04em}
  .card .accent{position:absolute;inset:0 0 auto 0;height:3px}
  .pill{display:inline-block;padding:.18rem .6rem;border-radius:999px;font-size:.7rem;font-weight:700}
  .b-ok{background:rgba(34,197,94,.16);color:#4ade80}.b-warn{background:rgba(234,179,8,.16);color:#facc15}
  .b-crit,.b-stale{background:rgba(239,68,68,.16);color:#f87171}.b-unknown{background:rgba(125,140,170,.16);color:#9fb0c9}
  table{width:100%;border-collapse:collapse;font-size:.8rem}
  th{text-align:left;color:var(--mut);font-weight:600;padding:.5rem .7rem;border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--card)}
  td{padding:.5rem .7rem;border-bottom:1px solid #14223c} tr:hover td{background:rgba(56,189,248,.05)}
  .wrap{background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--bd);border-radius:1rem;padding:.7rem;max-height:420px;overflow:auto}
  .zrow{display:flex;align-items:center;justify-content:space-between;padding:.6rem .9rem;border-radius:.7rem;background:#0d1830;border:1px solid var(--bd)}
  .dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:.5rem}
  .muted{color:var(--mut)} a.lnk{color:var(--acc)} svg{display:block;width:100%}
  .gauge-wrap{display:flex;flex-direction:column;align-items:center;gap:.3rem}
  .chip{display:inline-flex;align-items:center;gap:.4rem;padding:.4rem .7rem;border-radius:.7rem;background:#0d1830;border:1px solid var(--bd);font-size:.8rem}
  .err{color:var(--crit);font-size:.85rem}
  .legend{display:flex;gap:1rem;flex-wrap:wrap;font-size:.75rem;color:var(--mut);margin-top:.4rem}
  .legend i{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:.35rem}
</style></head>
<body>
  <aside class="side">
    <div class="brand"><span class="logo">🌍</span><span>Dakar Pipeline</span></div>
    <nav class="nav" id="nav"></nav>
    <div class="foot">auto-refresh 5 s<br><a class="lnk" href="/metrics">/metrics</a> · <a class="lnk" href="/api/overview">/api/overview</a></div>
  </aside>
  <main class="main">
    <div class="top">
      <h1><span class="pulse"></span> <span id="ptitle">Vue d'ensemble</span></h1>
      <div class="sub">MAJ <span id="ts">…</span></div>
    </div>
    <p class="lead" id="plead"></p>
    <p id="err" class="err"></p>
    <div id="view"></div>
  </main>

<script>
const $=id=>document.getElementById(id);
const PAGES=[
  {id:'overview',ic:'🛰️',label:"Vue d'ensemble",lead:"Santé globale du pipeline en un coup d'œil."},
  {id:'ingestion',ic:'📥',label:'Ingestion & Workers',lead:"Flux MQTT entrant, débit et état des workers temps réel."},
  {id:'data',ic:'🗄️',label:'Données & Capteurs',lead:"Volumétrie des tables et activité de chaque capteur."},
  {id:'quality',ic:'✅',label:'Qualité pipeline',lead:"Indicateurs Q1–Q6 du monitoring et leur évolution."},
  {id:'models',ic:'🧠',label:'Modèles & ML',lead:"Modèles entraînés, calibration et performances."},
  {id:'air',ic:'🌫️',label:"Qualité de l'air",lead:"Indice et polluants par zone de Dakar."},
  {id:'events',ic:'🚨',label:'Événements',lead:"Anomalies détectées et alertes générées."},
];
let D={}, cur='overview';

// ── helpers ──
const fmt=n=>n==null?'—':Number(n).toLocaleString('fr-FR');
const ago=iso=>{if(!iso)return'—';const s=(Date.now()-new Date(iso))/1000;
  if(s<60)return Math.round(s)+'s';if(s<3600)return Math.round(s/60)+'min';return Math.round(s/3600)+'h';};
const cls=h=>({ok:'b-ok',warn:'b-warn',crit:'b-crit',stale:'b-stale',unknown:'b-unknown'}[h]||'b-unknown');
const card=(v,l,c,sub)=>`<div class="card"><div class="accent" style="background:${c||'#38bdf8'}"></div>
   <div class="v" style="color:${c||'#e8eef7'}">${v}</div><div class="l">${l}</div>${sub?`<div class="sub" style="margin-top:.3rem">${sub}</div>`:''}</div>`;

// area chart (filled) from numeric array
function area(arr,color='#38bdf8',h=120){
  if(!arr||!arr.length)return '<div class="muted" style="padding:1rem">aucune donnée</div>';
  const w=600,max=Math.max(...arr,1),n=arr.length,dx=w/(n-1||1);
  let p=arr.map((v,i)=>`${(i*dx).toFixed(1)},${(h-4-(v/max)*(h-12)).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="height:${h}px">
    <defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${color}" stop-opacity=".45"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <polyline points="0,${h} ${p} ${w},${h}" fill="url(#ag)" stroke="none"/>
    <polyline points="${p}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
}
// vertical bars from [{label,value,color}]
function barsV(items,h=180){
  if(!items||!items.length)return '<div class="muted" style="padding:1rem">aucune donnée</div>';
  const max=Math.max(...items.map(i=>i.value||0),1),bw=100/items.length;
  return `<svg viewBox="0 0 100 ${h}" preserveAspectRatio="none" style="height:${h}px">`+
    items.map((it,i)=>{const bh=Math.max(1,((it.value||0)/max)*(h-26));
      return `<rect x="${(i*bw+bw*0.15).toFixed(2)}" y="${(h-20-bh).toFixed(1)}" width="${(bw*0.7).toFixed(2)}" height="${bh.toFixed(1)}" rx="1.5" fill="${it.color||'#38bdf8'}"/>`;}).join('')+
    `</svg><div style="display:flex">`+items.map(it=>`<div style="flex:1;text-align:center;font-size:.6rem;color:var(--mut);overflow:hidden">${it.label}</div>`).join('')+`</div>`;
}
// horizontal bars [{label,value,color,unit}]
function barsH(items){
  if(!items||!items.length)return '<div class="muted" style="padding:1rem">aucune donnée</div>';
  const max=Math.max(...items.map(i=>i.value||0),1);
  return items.map(it=>`<div style="margin:.45rem 0">
    <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:.2rem">
      <span>${it.label}</span><span class="muted">${fmt(it.value)}${it.unit||''}</span></div>
    <div style="height:9px;border-radius:6px;background:#0d1830;overflow:hidden">
      <div style="height:100%;width:${((it.value||0)/max*100).toFixed(1)}%;background:${it.color||'#38bdf8'};border-radius:6px"></div></div></div>`).join('');
}
// semicircle gauge 0..max
function gauge(val,max,label,color){
  const pct=Math.max(0,Math.min(1,(val||0)/max)), a=Math.PI*(1-pct), r=46,cx=60,cy=56;
  const x=cx+r*Math.cos(a), y=cy-r*Math.sin(a);
  const big=pct>0.5?1:0;
  return `<div class="gauge-wrap"><svg viewBox="0 0 120 70" style="height:90px">
    <path d="M14,56 A46,46 0 0,1 106,56" fill="none" stroke="#16243f" stroke-width="9" stroke-linecap="round"/>
    <path d="M14,56 A46,46 0 ${big},1 ${x.toFixed(1)},${y.toFixed(1)}" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"/>
    <text x="60" y="50" text-anchor="middle" fill="#e8eef7" font-size="17" font-weight="800">${val==null?'—':val}</text></svg>
    <div class="l" style="text-align:center">${label}</div></div>`;
}
// multi-series line chart from history rows [{t,...}], series=[{key,color,label}]
function lines(rows,series,h=200){
  if(!rows||rows.length<2)return '<div class="muted" style="padding:1rem">historique insuffisant</div>';
  const w=600,n=rows.length,dx=w/(n-1);
  let allv=[]; series.forEach(s=>rows.forEach(r=>{if(r[s.key]!=null)allv.push(r[s.key])}));
  const max=Math.max(...allv,1),min=Math.min(...allv,0),rng=(max-min)||1;
  const sv=series.map(s=>{const pts=rows.map((r,i)=>r[s.key]==null?null:`${(i*dx).toFixed(1)},${(h-10-((r[s.key]-min)/rng)*(h-20)).toFixed(1)}`).filter(Boolean).join(' ');
    return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2"/>`;}).join('');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="display:block;width:100%;max-width:100%;height:${h}px;overflow:hidden">${sv}</svg>
    <div class="legend">`+series.map(s=>`<span><i style="background:${s.color}"></i>${s.label}</span>`).join('')+`</div>`;
}
// donut from [{label,value,color}]
function donut(segs,h=180){
  const tot=segs.reduce((a,b)=>a+(b.value||0),0);
  if(!tot)return '<div class="muted" style="padding:1rem">aucune donnée</div>';
  let acc=0,r=52,cx=70,cy=70,paths='';
  segs.forEach(s=>{const frac=(s.value||0)/tot,a0=2*Math.PI*acc-Math.PI/2,a1=2*Math.PI*(acc+frac)-Math.PI/2;acc+=frac;
    const x0=cx+r*Math.cos(a0),y0=cy+r*Math.sin(a0),x1=cx+r*Math.cos(a1),y1=cy+r*Math.sin(a1),big=frac>0.5?1:0;
    paths+=`<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${big},1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="${s.color}" stroke="#0b1426" stroke-width="2"/>`;});
  return `<div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
    <svg viewBox="0 0 140 140" style="width:140px;height:140px;flex:none">${paths}<circle cx="70" cy="70" r="30" fill="#0b1426"/>
    <text x="70" y="76" text-anchor="middle" fill="#e8eef7" font-size="18" font-weight="800">${tot}</text></svg>
    <div>`+segs.map(s=>`<div style="font-size:.8rem;margin:.2rem 0"><span class="dot" style="background:${s.color}"></span>${s.label} <span class="muted">(${s.value})</span></div>`).join('')+`</div></div>`;
}

// ── pages ──
const V={};
V.overview=d=>{
  const st=d.db_stats||{},wok=(d.workers||[]).filter(w=>w.ok).length,wt=(d.workers||[]).length;
  return `<div class="grid kpis">
    ${card(fmt((d.ingestion_rate||[]).reduce((a,b)=>a+b,0)),'Msgs ingérés (60min)','#38bdf8')}
    ${card(`${st.sensors_active??'—'}/${st.sensors_total??'—'}`,'Capteurs actifs','#22c55e')}
    ${card(fmt(st.predictions),'Prédictions','#818cf8')}
    ${card(fmt(st.anomalies),'Anomalies','#f472b6')}
    ${card(fmt(st.alerts),'Alertes',st.alerts>0?'#facc15':'#e8eef7')}
    ${card(`${wok}/${wt}`,'Workers up',wok===wt?'#22c55e':'#f87171')}</div>
    <h2>Débit d'ingestion · 60 min</h2><div class="card">${area(d.ingestion_rate,'#38bdf8',130)}
      <div class="sub">total ${fmt((d.ingestion_rate||[]).reduce((a,b)=>a+b,0))} msgs · pic ${Math.max(0,...(d.ingestion_rate||[]))}/min</div></div>
    <div class="grid two"><div><h2>Santé des flows</h2><div class="grid cards">${(d.flows||[]).map(f=>`<div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center"><strong>${f.name}</strong><span class="pill ${cls(f.health)}">${f.health}</span></div>
        <div class="l">dernier passage : ${ago(f.last_run)}</div></div>`).join('')}</div></div>
      <div><h2>Top zones · PM2.5</h2><div class="wrap">${barsH((d.zones||[]).slice(0,6).map(z=>({label:z.name,value:z.pm25,unit:' µg',color:z.color})))}</div></div></div>`;
};
V.ingestion=d=>{
  const ps=(d.sensors||[]).slice().sort((a,b)=>b.messages_today-a.messages_today);
  return `<h2>Débit MQTT entrant · 60 min</h2><div class="card">${area(d.ingestion_rate,'#38bdf8',150)}
    <div class="sub">total ${fmt((d.ingestion_rate||[]).reduce((a,b)=>a+b,0))} msgs · pic ${Math.max(0,...(d.ingestion_rate||[]))}/min</div></div>
    <h2>Workers (supervisord)</h2><div class="grid cards">${(d.workers||[]).map(w=>`<div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center"><strong>${w.name}</strong><span class="pill ${w.ok?'b-ok':'b-crit'}">${w.state}</span></div>
      <div class="l">${w.uptime||'—'}</div></div>`).join('')||'<div class="muted">indisponible</div>'}</div>
    <h2>Messages du jour par capteur</h2><div class="wrap">${barsH(ps.map(s=>({label:s.id,value:s.messages_today,color:s.status==='active'?'#22c55e':'#64748b'})))}</div>`;
};
V.data=d=>{
  const st=d.db_stats||{};
  const tables=[['Capteurs',st.sensors_total,'#38bdf8'],['Features',st.features,'#818cf8'],['Prédictions',st.predictions,'#22c55e'],
    ['Kriging',st.kriging,'#06b6d4'],['Anomalies',st.anomalies,'#f472b6'],['Alertes',st.alerts,'#facc15']];
  return `<h2>Volumétrie des tables</h2><div class="card">${barsV(tables.map(t=>({label:t[0],value:t[1]||0,color:t[2]})),200)}</div>
    <h2>Capteurs du réseau</h2><div class="wrap"><table>
      <tr><th>Capteur</th><th>Zone</th><th>Statut</th><th>Vu</th><th>Msgs/j</th></tr>
      ${(d.sensors||[]).map(s=>`<tr><td>${s.id}</td><td>${s.zone}</td>
        <td><span class="pill ${s.status==='active'?'b-ok':'b-unknown'}">${s.status}</span></td>
        <td>${ago(s.last_seen)}</td><td>${fmt(s.messages_today)}</td></tr>`).join('')||'<tr><td colspan=5 class="muted">aucun</td></tr>'}</table></div>`;
};
V.quality=d=>{
  const m=(d.monitoring&&d.monitoring.latest)||{},hist=(d.monitoring&&d.monitoring.history)||[];
  const g=[['Q1 couverture',m.Q1_coverage,2,'#38bdf8'],['Q2 calibration',m.Q2_calibration_rate,1,'#22c55e'],
    ['Q3 RMSE 1h',m.Q3_rmse_1h,50,'#818cf8'],['Q4 RMSE 24h',m.Q4_rmse_24h,50,'#a78bfa'],
    ['Q5 fausses alarmes',m.Q5_false_alarm_rate,1,'#facc15'],['Q6 latence p95',m.Q6_pipeline_latency_p95_ms,500,'#f472b6']];
  return `<h2>Indicateurs qualité (Q1–Q6)</h2><div class="grid cards">
    ${g.map(x=>`<div class="card">${gauge(x[1]==null?null:Math.round(x[1]*100)/100,x[2],x[0],x[3])}</div>`).join('')}</div>
    <h2>Évolution Q1 (couverture) & Q2 (calibration)</h2><div class="card">
    ${lines(hist,[{key:'Q1_coverage',color:'#38bdf8',label:'Q1 couverture'},{key:'Q2_calibration_rate',color:'#22c55e',label:'Q2 calibration'}],200)}</div>`;
};
V.models=d=>{
  const c=d.calibration||{};
  return `<div class="grid kpis">
    ${card((d.models||[]).length,'Modèles enregistrés','#818cf8')}
    ${card((d.models||[]).filter(m=>m.active).length,'Modèles actifs','#22c55e')}
    ${card(c.avg_r2??'—','R² moyen calibration','#38bdf8')}
    ${card(fmt(c.count),'Calibrations récentes','#facc15')}</div>
    <h2>Modèles ML</h2><div class="wrap"><table>
      <tr><th>Nom</th><th>Type</th><th>Version</th><th>Actif</th><th>Entraîné</th></tr>
      ${(d.models||[]).map(m=>`<tr><td>${m.name}</td><td>${m.type}</td><td>${m.version||'—'}</td>
        <td>${m.active?'<span class="pill b-ok">oui</span>':'<span class="pill b-unknown">non</span>'}</td><td>${ago(m.trained)}</td></tr>`).join('')||'<tr><td colspan=5 class="muted">aucun</td></tr>'}</table></div>
    <h2>Calibration récente</h2><div class="wrap"><table>
      <tr><th>Heure</th><th>Capteur</th><th>Polluant</th><th>coef_a</th><th>coef_b</th><th>R²</th></tr>
      ${(c.recent||[]).map(r=>`<tr><td>${ago(r.time)}</td><td>${r.sensor}</td><td>${r.pollutant}</td>
        <td>${r.coef_a??'—'}</td><td>${r.coef_b??'—'}</td><td>${r.r2??'—'}</td></tr>`).join('')||'<tr><td colspan=6 class="muted">aucune</td></tr>'}</table></div>`;
};
V.air=d=>{
  const zs=d.zones||[],bands={};
  zs.forEach(z=>{if(z.pm25!=null){bands[z.band]=bands[z.band]||{label:z.band,value:0,color:z.color};bands[z.band].value++;}});
  return `<div class="grid two"><div><h2>Classement PM2.5</h2><div class="wrap">${barsH(zs.map(z=>({label:z.name,value:z.pm25,unit:' µg',color:z.color})))}</div></div>
    <div><h2>Répartition des niveaux</h2><div class="card">${donut(Object.values(bands))}</div></div></div>
    <h2>Zones</h2><div class="grid cards">${zs.map(z=>`<div class="card"><div class="accent" style="background:${z.color}"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div><strong>${z.name}</strong><div class="l">${z.band}</div></div>
        <div style="text-align:right"><div class="v" style="font-size:1.5rem;color:${z.color}">${z.pm25??'—'}</div><div class="l">µg/m³</div></div></div></div>`).join('')||'<div class="muted">pas de données</div>'}</div>`;
};
V.events=d=>{
  const sev={}; (d.recent_alerts||[]).forEach(a=>{const k=a.gravite||'—';sev[k]=sev[k]||{label:k,value:0,color:k==='danger'?'#ef4444':k==='warning'?'#eab308':'#64748b'};sev[k].value++;});
  return `<div class="grid two"><div><h2>Anomalies récentes</h2><div class="wrap"><table>
      <tr><th>Heure</th><th>Capteur</th><th>Zone</th><th>Poll.</th><th>Val.</th><th>Score</th></tr>
      ${(d.recent_anomalies||[]).map(a=>`<tr><td>${ago(a.time)}</td><td>${a.sensor}</td><td>${a.zone}</td><td>${a.pollutant}</td><td>${a.value??'—'}</td><td>${a.score??'—'}</td></tr>`).join('')||'<tr><td colspan=6 class="muted">aucune</td></tr>'}</table></div></div>
    <div><h2>Répartition gravité alertes</h2><div class="card">${donut(Object.values(sev))}</div></div></div>
    <h2>Alertes récentes</h2><div class="wrap"><table>
      <tr><th>Heure</th><th>Gravité</th><th>Zone</th><th>Type</th><th>Statut</th></tr>
      ${(d.recent_alerts||[]).map(a=>{const g=a.gravite==='danger'?'b-crit':a.gravite==='warning'?'b-warn':'b-unknown';
        return `<tr><td>${ago(a.time)}</td><td><span class="pill ${g}">${a.gravite||'—'}</span></td><td>${a.zone}</td><td>${a.type||'—'}</td><td>${a.statut||'—'}</td></tr>`;}).join('')||'<tr><td colspan=5 class="muted">aucune</td></tr>'}</table></div>`;
};

// ── routing & render ──
function buildNav(){
  $('nav').innerHTML=PAGES.map(p=>`<a href="#${p.id}" data-id="${p.id}"><span class="ic">${p.ic}</span><span class="lbl">${p.label}</span></a>`).join('');
}
function render(){
  const p=PAGES.find(x=>x.id===cur)||PAGES[0];
  document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('active',a.dataset.id===cur));
  $('ptitle').textContent=p.label; $('plead').textContent=p.lead;
  if(D.generated_at)$('ts').textContent=new Date(D.generated_at).toLocaleTimeString('fr-FR');
  try{ $('view').innerHTML=(V[cur]||V.overview)(D); }catch(e){ $('err').textContent='Rendu: '+e.message; }
}
function route(){ cur=(location.hash||'#overview').slice(1); if(!PAGES.find(p=>p.id===cur))cur='overview'; render(); }
async function load(){ try{ D=await (await fetch('/api/overview')).json(); $('err').textContent=''; render(); }
  catch(e){ $('err').textContent='Connexion perdue — '+e.message; } }
window.addEventListener('hashchange',route);
buildNav(); route(); load(); setInterval(load,5000);
</script>
</body></html>
"""
