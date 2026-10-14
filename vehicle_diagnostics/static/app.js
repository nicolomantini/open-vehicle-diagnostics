'use strict';
const $ = id => document.getElementById(id);
const histories = new Map();
let schema = '', lastStamp = null, lastMode = '', lastFaults = '', lastRecording = null;
const token = document.querySelector('meta[name="api-token"]').content;
function text(tag, value, cls) { const e = document.createElement(tag); e.textContent = value; if (cls) e.className = cls; return e; }
async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) { let detail; try { detail = (await response.json()).error; } catch {} throw new Error(detail || `Request failed (${response.status})`); }
  return response.json();
}
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
async function act(action, args = {}) {
  try { await api('/api/action', {method:'POST', headers:{'Content-Type':'application/json','X-Diagnostics-Token':token}, body:JSON.stringify({action,...args})}); error(null); }
  catch (e) { error(e.message); }
}
async function refreshPorts() {
  try { const ports = await api('/api/ports'); const selected = $('port').value; $('port').replaceChildren(new Option('Auto-detect', ''));
    for (const port of ports) $('port').add(new Option(`${port.device} · ${port.description}`, port.device));
    if (ports.some(p => p.device === selected)) $('port').value = selected;
  } catch(e) { error(e.message); }
}
function graph(canvas, data) {
  const ratio = window.devicePixelRatio || 1, width = canvas.clientWidth, height = 76;
  canvas.width = width * ratio; canvas.height = height * ratio;
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
  const valid = data.filter(Number.isFinite); if (!valid.length) return 'No numeric responses';
  const low = Math.min(...valid), high = Math.max(...valid), span = high - low || 1;
  ctx.strokeStyle = '#293a4f'; ctx.beginPath(); ctx.moveTo(0,height-8);ctx.lineTo(width,height-8);ctx.stroke();
  ctx.strokeStyle = '#81e2c4'; ctx.lineWidth = 2; ctx.beginPath(); let gap = true;
  data.forEach((v,i) => { if (!Number.isFinite(v)) {gap=true;return;} const x=i/89*width, y=height-8-(v-low)/span*(height-16); if(gap)ctx.moveTo(x,y);else ctx.lineTo(x,y);gap=false; });ctx.stroke();
  return `${low.toFixed(1)} – ${high.toFixed(1)} · ${data.length} samples`;
}
function render(state) {
  $('mode').textContent = state.mode.toUpperCase(); $('mode').className = `badge ${state.mode}`;
  $('status').textContent = state.status;
  const live = state.mode === 'vehicle' || state.mode === 'simulator';
  $('record').disabled = !live || !!state.recording; $('stop-record').disabled = !state.recording; $('faults').disabled = !live;
  $('notice').textContent = state.mode === 'simulator' ? 'SIMULATOR · All readings and fault codes are synthetic. This is not a vehicle test.' : state.mode === 'replay' ? `REPLAY · Recorded ${state.replay_source} data. No live vehicle queries.` : state.mode === 'vehicle' ? 'VEHICLE · Standard OBD-II readings. Unsupported sensors are omitted; unanswered queries show “No data”.' : 'DISCONNECTED · No live vehicle data.';
  $('connection-detail').textContent = state.protocol ? `Protocol: ${state.protocol} · ${state.sensors.length} dashboard channels discovered` : 'Select a source and connect. Serial devices listed are candidates, not confirmed OBD adapters.';
  $('sample-time').textContent = state.timestamp ? `Sample: ${new Date(state.timestamp).toLocaleString()} · ${Math.max(0,Math.round((Date.now()-Date.parse(state.timestamp))/1000))}s ago` : 'Waiting for a data source';
  $('record-status').textContent = state.recording ? '● Recording locally' : '';
  error(state.error);
  const nextSchema = JSON.stringify([state.stream_id,state.sensors]);
  if (schema !== nextSchema || lastMode !== state.mode || (lastStamp && state.timestamp && state.timestamp < lastStamp)) {
    schema = nextSchema; lastMode = state.mode; lastStamp = null; histories.clear(); $('sensors').replaceChildren();
    for (const s of state.sensors) {
      const card = text('article','', 'sensor'); card.append(text('h3', s.label));
      const reading = text('span','—','reading'); reading.id = `value-${s.key}`; card.append(reading, text('span',s.unit,'unit'));
      const canvas = document.createElement('canvas'); canvas.id=`graph-${s.key}`; canvas.setAttribute('aria-label',`${s.label} trend`); card.append(canvas);
      const scale = text('div','','scale'); scale.id=`scale-${s.key}`;card.append(scale);$('sensors').append(card);histories.set(s.key,[]);
    }
    if (!state.sensors.length) $('sensors').append(text('div','Connect a source to discover supported dashboard sensors.','empty'));
  }
  for (const s of state.sensors) {
    const v = state.readings[s.key]; $('value-'+s.key).textContent = Number.isFinite(v) ? v.toLocaleString(undefined,{maximumFractionDigits:1}) : 'No data';
    const data = histories.get(s.key); if (state.timestamp && state.timestamp !== lastStamp) {data.push(v ?? null);if(data.length>90)data.shift();}
    $('scale-'+s.key).textContent=graph($('graph-'+s.key),data);
  }
  lastStamp = state.timestamp;
  $('commands').textContent = state.supported_commands.length ? state.supported_commands.join(', ') : 'No vehicle discovery. The simulator does not establish vehicle support.';
  if (JSON.stringify(state.faults) !== lastFaults) {
    lastFaults=JSON.stringify(state.faults);$('fault-results').replaceChildren();$('report').hidden=!state.faults;
    if (!state.faults) $('fault-results').append(text('p','No fault-code query yet.'));
    else { $('fault-results').append(text('p',`${state.faults.source_mode.toUpperCase()} · ${new Date(state.faults.timestamp).toLocaleString()}`));
      for (const [group,result] of Object.entries(state.faults.results)) {const box=text('div','','fault-group');box.append(text('strong',group.toUpperCase()));
        if (result.status !== 'ok') box.append(text('p','No response — this does not establish that there are no faults.'));
        else if (!result.codes.length) box.append(text('p','No codes returned for this category.'));
        for (const [code,desc] of result.codes) box.append(text('div',`${code} · ${desc || 'Description unavailable'}`,'fault-code'));
        $('fault-results').append(box);
      }
    }
  }
  if (lastRecording !== state.recording) { lastRecording=state.recording; refreshRecordings(); }
}
async function refreshRecordings() {
  try {const recordings=await api('/api/recordings');$('recordings').replaceChildren();
    if (!recordings.length) $('recordings').append(text('p','No recordings yet. Start a source, then choose Start recording.'));
    for (const r of recordings) {const box=text('div','','recording');box.append(text('p',`${new Date(r.started).toLocaleString()} · ${r.mode.toUpperCase()} · ${r.samples} samples${r.ended?'':' · open / interrupted'}`));
      const link=text('a','Export CSV');link.href=`/api/recordings/${r.id}/csv`;box.append(link);
      const replay=text('button','Replay');replay.disabled=!r.samples;replay.onclick=()=>act('replay',{id:r.id});box.append(replay);$('recordings').append(box);
    }
  } catch(e) {error(e.message);}
}
$('connect').onclick=()=>act('connect',{mode:$('source').value,port:$('source').value==='vehicle'?$('port').value:null,baudrate:Number($('baud').value)||null});
$('disconnect').onclick=()=>act('disconnect');$('refresh').onclick=refreshPorts;
$('record').onclick=()=>act('record_start');$('stop-record').onclick=()=>act('record_stop');$('faults').onclick=()=>act('faults');$('recordings-refresh').onclick=refreshRecordings;
async function poll() {try {render(await api('/api/status'));} catch(e){$('status').textContent='Dashboard offline';error(e.message);} finally {setTimeout(poll,750);}}
refreshPorts();refreshRecordings();poll();
