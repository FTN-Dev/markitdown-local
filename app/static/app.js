const drop = document.getElementById('drop');
const fileinput = document.getElementById('fileinput');
const list = document.getElementById('list');
const downloadAll = document.getElementById('downloadAll');
const processAllBtn = document.getElementById('processAll');
const preview = document.getElementById('preview');
const previewText = document.getElementById('previewText');
const formatsEl = document.getElementById('formats');

let currentJob = null;
let pollTimer = null;

fetch('/api/formats').then(r=>r.json()).then(d=>{
  formatsEl.textContent = `OCR: ${d.ocr_active?'aktif':'nonaktif'} · max ${d.max_file_mb}MB/file · ${d.max_files} file/batch`;
}).catch(()=>{});

function addFiles(files){
  if(!files.length) return;
  const fd = new FormData();
  for(const f of files) fd.append('files', f);
  fd.append('extract_images', document.getElementById('extract').checked);
  fetch('/api/convert', {method:'POST', body:fd})
    .then(r=>r.json()).then(d=>{
      currentJob = d.job_id;
      renderItems(d.items);
      startPoll();
      downloadAll.disabled = false;
      processAllBtn.disabled = false;
    }).catch(e=>alert('Upload gagal: '+e));
}

drop.addEventListener('dragover', e=>{e.preventDefault(); drop.classList.add('drag');});
drop.addEventListener('dragleave', ()=>drop.classList.remove('drag'));
drop.addEventListener('drop', e=>{e.preventDefault(); drop.classList.remove('drag'); addFiles(e.dataTransfer.files);});
fileinput.addEventListener('change', e=>{ addFiles(e.target.files); fileinput.value='';});
document.getElementById('clear').addEventListener('click', ()=>{ list.innerHTML=''; currentJob=null; downloadAll.disabled=true; processAllBtn.disabled=true; preview.hidden=true; });

processAllBtn.addEventListener('click', async ()=>{
  if(!currentJob) return;
  await fetch('/api/jobs/'+currentJob+'/process', {method:'POST'});
});

function renderItems(items){
  list.innerHTML = '';
  for(const it of items){
    const div = document.createElement('div');
    div.className = 'item';
    div.dataset.id = it.id;
    div.innerHTML = `<div class="name" title="${escapeHtml(it.name)}">${escapeHtml(it.name)}</div>
      <span class="status ${it.status}">${it.status}</span>
      <span class="meta"></span>
      <span class="actions"></span>`;
    list.appendChild(div);
    updateItemActions(it);
  }
}

function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function updateItemActions(it){
  const el = list.querySelector(`[data-id="${it.id}"]`);
  if(!el) return;
  const actions = el.querySelector('.actions');
  if(it.status==='queued'){
    actions.innerHTML = `<button class="btn small-btn" data-proc="${it.id}">Proses</button>
      <button class="btn secondary small-btn" data-cancel="${it.id}" title="Batalkan">X</button>`;
    actions.querySelector(`[data-proc="${it.id}"]`).addEventListener('click', async ()=>{
      await fetch(`/api/jobs/${currentJob}/items/${it.id}/process`, {method:'POST'});
    });
    actions.querySelector(`[data-cancel="${it.id}"]`).addEventListener('click', async ()=>{
      await fetch(`/api/jobs/${currentJob}/items/${it.id}`, {method:'DELETE'});
    });
  } else if(it.status==='done'){
    actions.innerHTML = `<button class="btn secondary small-btn" data-preview="${it.id}">Preview</button>
      <a class="dl" href="/api/jobs/${currentJob}/files/${it.id}" download>Download</a>`;
    const pb = actions.querySelector('[data-preview]');
    pb.addEventListener('click', async ()=>{
      const t = await fetch(`/api/jobs/${currentJob}/files/${it.id}`).then(x=>x.text());
      preview.hidden = false;
      previewText.textContent = t;
    });
  } else if(it.status==='failed'){
    actions.innerHTML = `<span class="muted small">${escapeHtml(it.error||'gagal')}</span>`;
  } else {
    actions.innerHTML = '';
  }
}

function startPoll(){
  if(pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async ()=>{
    if(!currentJob) return;
    const r = await fetch('/api/jobs/'+currentJob);
    const d = await r.json();
    // remove cancelled items from DOM
    const ids = new Set(d.items.map(i=>i.id));
    for(const el of [...list.querySelectorAll('.item')]){
      if(!ids.has(el.dataset.id)) el.remove();
    }
    for(const it of d.items){
      const el = list.querySelector(`[data-id="${it.id}"]`);
      if(!el) { renderOne(it); continue; }
      const st = el.querySelector('.status');
      st.textContent = it.status;
      st.className = 'status '+it.status;
      const meta = el.querySelector('.meta');
      meta.textContent = it.converter ? `${it.converter} ${it.seconds||''}s` : (it.error||'');
      updateItemActions(it);
    }
    // disable processAll if no queued
    const hasQueued = d.items.some(i=>i.status==='queued');
    processAllBtn.disabled = !hasQueued;
    if(d.status==='done' || d.status==='failed'){
      const pending = d.items.some(i=>i.status==='queued'||i.status==='running');
      if(!pending) clearInterval(pollTimer);
    }
  }, 1000);
}

function renderOne(it){
  const div = document.createElement('div');
  div.className = 'item';
  div.dataset.id = it.id;
  div.innerHTML = `<div class="name" title="${escapeHtml(it.name)}">${escapeHtml(it.name)}</div>
    <span class="status ${it.status}">${it.status}</span>
    <span class="meta"></span>
    <span class="actions"></span>`;
  list.appendChild(div);
  updateItemActions(it);
}

downloadAll.addEventListener('click', ()=>{
  if(currentJob) window.location.href = '/api/jobs/'+currentJob+'/download';
});
