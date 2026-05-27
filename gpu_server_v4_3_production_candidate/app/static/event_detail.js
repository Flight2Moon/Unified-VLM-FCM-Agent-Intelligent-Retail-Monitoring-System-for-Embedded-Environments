async function getJSON(url){ const r=await fetch(url); if(!r.ok) throw new Error(await r.text()); return await r.json(); }
function pretty(x){ return JSON.stringify(x,null,2); }
function esc(s){ return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function linkAsset(v, label){
  if(!v || typeof v !== 'string') return '';
  if(v.startsWith('/api/events/')) return `<a href="${esc(v)}" target="_blank">${esc(label||v.split('/').pop())}</a>`;
  return esc(v);
}
function renderQuality(data){
  const rt=data.vlm_runtime||{};
  const status = rt.called ? (rt.valid_json_calls>0 ? 'SUCCESS' : 'NO_VALID_JSON') : 'NOT_CALLED';
  document.getElementById('quality').innerHTML = `
    <div class="quality-grid">
      <div><b>VLM Provider</b><span>${esc(rt.provider||'unknown')}</span></div>
      <div><b>Model</b><span>${esc(rt.model||'')}</span></div>
      <div><b>Status</b><span class="badge ${status==='SUCCESS'?'ok':(status==='NOT_CALLED'?'wait':'bad')}">${status}</span></div>
      <div><b>Valid JSON</b><span>${esc(rt.valid_json_calls||0)} / ${esc((rt.calls||[]).length)}</span></div>
    </div>`;
}
function renderAssets(data){
  const div=document.getElementById('assets'); div.innerHTML='';
  const assets=data.evidence_assets || {};
  if(assets.overlay && typeof assets.overlay==='string' && assets.overlay.startsWith('/api/events/')){
    const card=document.createElement('div'); card.className='asset-card';
    card.innerHTML=`<h3>Overlay</h3><a href="${esc(assets.overlay)}" target="_blank"><img src="${esc(assets.overlay)}" /></a>`;
    div.appendChild(card);
  }
  const crops=assets.union_crops || {};
  for(const [pair,url] of Object.entries(crops).slice(0,12)){
    if(typeof url !== 'string' || !url.startsWith('/api/events/')) continue;
    const card=document.createElement('div'); card.className='asset-card';
    card.innerHTML=`<h3>${esc(pair)}</h3><a href="${esc(url)}" target="_blank"><img src="${esc(url)}" /></a>`;
    div.appendChild(card);
  }
  if(!div.innerHTML) div.textContent='No image evidence asset found.';
}
function renderRelations(data){
  const div=document.getElementById('relations'); div.innerHTML='';
  const exps=data.relation_explanations || [];
  if(!exps.length){ div.textContent='No relation explanation available yet.'; return; }
  for(const [idx,e] of exps.entries()){
    const edge=e.edge || {};
    const subj=e.subject || {}; const obj=e.object || {};
    const dbg=e.debug_call || null;
    const art=(dbg && dbg.artifacts) || {};
    const pair=(e.geometry_evidence && e.geometry_evidence.candidate_pair) || null;
    const item=document.createElement('details'); item.className='relation-card'; item.open=idx<3;
    item.innerHTML=`
      <summary><b>${esc(edge.subject_id)}</b> — <span class="pill">${esc(edge.relation)}</span> → <b>${esc(edge.object_id)}</b> <span class="score">conf ${Number(edge.confidence||0).toFixed(3)}</span></summary>
      <div class="relation-body">
        <div class="kv"><b>Source</b><span>${esc(e.source_kind)}</span></div>
        <div class="kv"><b>Subject</b><span>${esc(subj.label||subj.id)} / bbox ${esc(JSON.stringify(subj.bbox||[]))}</span></div>
        <div class="kv"><b>Object</b><span>${esc(obj.label||obj.id)} / bbox ${esc(JSON.stringify(obj.bbox||[]))}</span></div>
        <h4>Why this edge was kept</h4>
        <ul>${(e.why_kept||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
        <h4>VLM evidence strings</h4>
        <ul>${(e.vlm_evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('') || '<li>No VLM evidence string. This may be a geometry edge.</li>'}</ul>
        ${e.scene_summary ? `<h4>Scene summary</h4><p>${esc(e.scene_summary)}</p>` : ''}
        <h4>Geometry evidence</h4>
        <pre>${esc(pretty({candidate_pair: pair, geometry_edges_same_pair: (e.geometry_evidence||{}).geometry_edges_same_pair || []}))}</pre>
        <h4>Debug artifacts</h4>
        <p>Prompt: ${linkAsset(art.prompt, 'open prompt')} &nbsp; Response: ${linkAsset(art.response, 'open raw response')}</p>
        <pre>${esc(pretty({debug_call: dbg, dropped_competing_edges: e.dropped_competing_edges || []}))}</pre>
      </div>`;
    div.appendChild(item);
  }
}
function renderVLMCalls(data){
  const div=document.getElementById('vlmCalls'); div.innerHTML='';
  const calls=(data.vlm_runtime||{}).calls || [];
  if(!calls.length){ div.innerHTML='<p class="muted">No VLM calls were executed.</p>'; return; }
  for(const c of calls){
    const art=c.artifacts||{};
    const ok=c.ok && c.json_parse_ok;
    const row=document.createElement('div'); row.className='call-row';
    row.innerHTML=`<b>${esc(c.call_id)}</b> <span class="badge ${ok?'ok':'bad'}">${ok?'valid':'failed'}</span>
      <small>${esc(c.type)} · http=${esc(c.status_code||'')} · parse=${esc(c.json_parse_ok)} · ${Number(c.latency_sec||0).toFixed(2)}s</small>
      <p>${linkAsset(art.prompt,'prompt')} ${linkAsset(art.response,'response')}</p>
      ${c.parse_error ? `<p class="error-text">${esc(c.parse_error)}</p>` : ''}`;
    div.appendChild(row);
  }
}
function renderLogs(data){
  const div=document.getElementById('logs'); div.innerHTML='';
  for(const l of data.logs || []){
    const row=document.createElement('div'); row.className='log-row';
    row.innerHTML=`<b>${esc(l.stage)}</b> <span>${esc(l.created_at)}</span><p>${esc(l.message||'')}</p>`;
    div.appendChild(row);
  }
}
function showNodePanel(node){
  const panel=document.getElementById('nodePanel');
  if(!node){ panel.innerHTML='<p class="muted">그래프 노드를 클릭하면 해당 장면의 crop/정보가 표시됩니다.</p>'; return; }
  const entity=node.entity||{};
  panel.innerHTML=`<h3>${esc(node.id)}</h3>
    <p><b>Label:</b> ${esc(entity.label||'')} · <b>Confidence:</b> ${Number(entity.confidence||0).toFixed(3)}</p>
    <p><b>BBox:</b> ${esc(JSON.stringify(entity.bbox||[]))}</p>
    ${node.image_url ? `<a href="${esc(node.image_url)}" target="_blank"><img class="node-preview" src="${esc(node.image_url)}" /></a>` : '<p class="muted">이 노드에 대한 crop 이미지를 만들 수 없습니다.</p>'}
    <pre>${esc(pretty(entity))}</pre>`;
}
async function renderGraph(){
  const g=await getJSON(`/api/events/${encodeURIComponent(window.EVENT_ID)}/graph`);
  const container=document.getElementById('graph');
  if(typeof vis === 'undefined'){
    container.innerHTML = `<pre>${esc(pretty(g))}</pre>`;
    return;
  }
  const nodes=new vis.DataSet(g.nodes||[]);
  const edges=new vis.DataSet(g.edges||[]);
  const data={nodes, edges};
  const options={
    nodes:{shape:'dot', size:20, font:{size:14}},
    edges:{font:{align:'middle'}, arrows:{to:{enabled:true}}, smooth:{type:'dynamic'}, color:{inherit:'from'}},
    groups:{person:{color:{background:'#dbeafe', border:'#2563eb'}}, detected_object:{color:{background:'#fef3c7', border:'#d97706'}}},
    physics:{barnesHut:{gravitationalConstant:-2600, springLength:150, springConstant:0.04}, stabilization:true},
    interaction:{hover:true, tooltipDelay:100}
  };
  const network=new vis.Network(container, data, options);
  showNodePanel(null);
  network.on('click', params => {
    if(params.nodes && params.nodes.length){
      const n=nodes.get(params.nodes[0]); showNodePanel(n);
    }
  });
}
async function main(){
  document.getElementById('eventTitle').textContent=window.EVENT_ID;
  const data=await getJSON(`/api/events/${encodeURIComponent(window.EVENT_ID)}/explain`);
  renderQuality(data);
  document.getElementById('summary').textContent=pretty({event:data.event, metadata:data.metadata, explainability:data.explainability});
  document.getElementById('scoring').textContent=pretty(data.scoring || {});
  document.getElementById('runtime').textContent=pretty(data.vlm_runtime || {});
  document.getElementById('uncertain').textContent=pretty(data.uncertain_relations || []);
  document.getElementById('rejected').textContent=pretty(data.rejected_relations || []);
  document.getElementById('dropped').textContent=pretty(data.dropped_edges || []);
  renderAssets(data); renderRelations(data); renderLogs(data); renderVLMCalls(data); await renderGraph();
}
main().catch(e=>{ document.body.insertAdjacentHTML('beforeend', `<pre class="error">${esc(e.stack||e)}</pre>`); });
