async function getJSON(url){ const r=await fetch(url); if(!r.ok) throw new Error(await r.text()); return await r.json(); }
function pretty(x){ return JSON.stringify(x,null,2); }
function esc(s){ return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function badgeStatus(status){
  const st=String(status||'unknown');
  const cls=st==='done'?'ok':(st.includes('fail')?'bad':(st.includes('queued')?'wait':'run'));
  return `<span class="badge ${cls}">${esc(st)}</span>`;
}
function eventMini(e){
  return `<div class="event-mini">
    <div><a href="/dashboard/events/${encodeURIComponent(e.event_id)}" target="_blank"><b>${esc(e.event_id)}</b></a></div>
    <div>${badgeStatus(e.status)} <span class="muted">${esc(e.decision||'UNKNOWN')}</span> <span class="score">${Number(e.score||0).toFixed(3)}</span></div>
    <small>${esc(e.camera_id||'cam?')} · ${esc(e.trigger_level||'')} · ${esc(e.created_at||'')}</small>
  </div>`;
}
async function loadHealth(){ document.getElementById('health').textContent=pretty(await getJSON('/health')); }
async function loadStorage(){ document.getElementById('storage').textContent=pretty(await getJSON('/api/storage/stats')); }
async function loadDataset(){ document.getElementById('dataset').textContent=pretty(await getJSON('/api/dataset/summary')); }
async function loadPolicy(){ document.getElementById('policy').textContent=pretty(await getJSON('/api/detection-policy')); }
async function loadEdgeNodes(){
  const data=await getJSON('/api/edge/nodes');
  const div=document.getElementById('edgeNodes'); div.innerHTML='';
  if(!data.nodes?.length){ div.innerHTML='<p class="muted">No heartbeat yet. Edge events can still arrive, but node liveness is unknown.</p>'; return; }
  for(const n of data.nodes){
    const item=document.createElement('div'); item.className='node-card';
    item.innerHTML=`<b>${esc(n.edge_id)}</b> ${badgeStatus(n.status)}<br/>
      <small>camera=${esc(n.camera_id||'')} · queue=${esc(n.queue_count)} · sent=${esc(n.sent_count)} · failed=${esc(n.failed_count)}</small><br/>
      <small>last heartbeat: ${esc(n.last_heartbeat_at||'')}</small>`;
    div.appendChild(item);
  }
}
async function loadPipeline(){
  const data=await getJSON('/api/events/status-summary?limit_per_group=12');
  const lanes=[['incoming','입력받은 파일'],['processing','처리하고 있는 파일'],['done','처리가 끝난 파일'],['failed','실패/복구 필요']];
  for(const [key] of lanes){
    const box=document.getElementById(`lane-${key}`);
    box.innerHTML=(data.groups[key]||[]).map(eventMini).join('') || '<p class="muted">없음</p>';
  }
  document.getElementById('pipelineCounts').textContent=pretty(data.counts||{});
}
async function loadEvents(){
  const data=await getJSON('/api/events/recent?limit=80');
  const tb=document.querySelector('#events tbody'); tb.innerHTML='';
  for(const e of data.events){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><a href="/dashboard/events/${encodeURIComponent(e.event_id)}" target="_blank">${esc(e.event_id)}</a><br/><small><a href="/api/events/${encodeURIComponent(e.event_id)}" target="_blank">raw JSON</a></small></td><td>${badgeStatus(e.status)}</td><td>${esc(e.decision)}</td><td>${Number(e.score||0).toFixed(3)}</td><td>${esc(e.source_type||'')}</td><td>${esc(e.created_at)}</td>`;
    tb.appendChild(tr);
  }
}
async function loadLabels(){
  const data=await getJSON('/api/detection-labels/stats');
  const tb=document.querySelector('#labels tbody'); tb.innerHTML='';
  for(const l of data.labels){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${esc(l.label)}</td><td>${l.count}</td><td>${Number(l.avg_conf||0).toFixed(3)}</td><td>${esc(l.last_seen_at||'')}</td><td><button onclick="quickLabel('${esc(l.label)}','ignore')">Ignore</button><button onclick="quickLabel('${esc(l.label)}','important')">Important</button></td>`;
    tb.appendChild(tr);
  }
}
async function loadReview(){
  const data=await getJSON('/api/dataset/samples?review_only=true&limit=20');
  const div=document.getElementById('review'); div.innerHTML='';
  for(const s of data.samples){
    const item=document.createElement('div'); item.className='sample';
    item.innerHTML=`<img src="/api/dataset/samples/${encodeURIComponent(s.sample_id)}/image"/><small>${esc(s.sample_id)}<br/>${esc(s.label)}</small><br/><button onclick="labelSample('${esc(s.sample_id)}','staff_uniform')">staff</button><button onclick="labelSample('${esc(s.sample_id)}','non_staff_uniform')">non-staff</button>`;
    div.appendChild(item);
  }
}
async function quickLabel(label,state){ await fetch('/api/detection-policy/label-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label,state})}); await loadPolicy(); await loadLabels(); }
async function setLabel(state){ const label=document.getElementById('labelInput').value.trim(); if(label) await quickLabel(label,state); }
async function labelSample(id,label){ await fetch(`/api/dataset/samples/${encodeURIComponent(id)}/label`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label,verified:true})}); await loadReview(); await loadDataset(); }
async function recoverStale(action='mark_failed'){
  const r=await fetch(`/api/events/recover-stale?action=${encodeURIComponent(action)}`,{method:'POST'});
  const data=await r.json(); alert(`Recovered ${data.recovered?.length||0} stale event(s).`); await loadAll();
}
async function loadAll(){ await Promise.all([loadHealth(),loadStorage(),loadDataset(),loadPolicy(),loadEvents(),loadLabels(),loadReview(),loadPipeline(),loadEdgeNodes()]); }
loadAll();
setInterval(()=>{ loadPipeline(); loadEvents(); loadEdgeNodes(); }, 2500);
let ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
ws.onmessage=(ev)=>{ try{const msg=JSON.parse(ev.data); console.log('ws',msg); loadPipeline(); loadEvents(); loadHealth(); loadEdgeNodes();}catch(e){} };
