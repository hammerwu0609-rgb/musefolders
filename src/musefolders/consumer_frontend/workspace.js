// D3 and Natural Earth geometry are bundled locally by consumer_ui.py.
const icons = {
 music:'M9 18V5l12-2v13M9 8l12-2M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Zm12-2a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Z',
 play:'m9 5 11 7-11 7Z', plus:'M12 5v14M5 12h14', check:'m5 12 4 4L19 6', close:'m6 6 12 12M6 18 18 6',
 settings:'M4 7h16M4 17h16M8 4v6M16 14v6', share:'M12 16V3m-5 5 5-5 5 5M5 13v7h14v-7',
 arrow:'M5 12h14m-6-6 6 6-6 6', down:'m6 10 6 6 6-6', reset:'M3 10a9 9 0 1 1 2 8M3 4v6h6',
 minus:'M5 12h14', left:'m15 5-7 7 7 7', right:'m9 5 7 7-7 7', up:'m6 14 6-6 6 6',
 download:'M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4', edit:'m16 3 5 5-12 12H4v-5Zm-2 2 5 5',
 previous:'M6 5v14m12-14-9 7 9 7Z', next:'M18 5v14M6 5l9 7-9 7Z', search:'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 6 6', globe:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-9 9h18M12 3c5 6 5 12 0 18-5-6-5-12 0-18'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.music}"/></svg>`;
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = n => `${Math.floor(n/60)}:${String(Math.round(n%60)).padStart(2,'0')}`;
const countries = [{id:'156',name:'中国',center:[104,35]},{id:'392',name:'日本',center:[138,37]},{id:'410',name:'韩国',center:[128,36]},{id:'840',name:'美国',center:[-100,38]},{id:'826',name:'英国',center:[-2,54]},{id:'276',name:'德国',center:[10,51]},{id:'250',name:'法国',center:[2,47]}];

export default function(component) {
 const root = component.parentElement.querySelector('#music-workspace');
 if (root._workspace) { root._workspace.update(component); return; }
 let data = component.data, send = component.setTriggerValue;
 let tab='map', filter=null, count=12, busy=false, rotation=[-110,-20,0], zoom=1, inputText='', playing=null, starBounds=null;
 let showConstellation=false, focusedId=null, replayEntry=null, drawerOpen=false, pendingFlight=null, lastToken=0;
 let libraryCount=12, selectionCount=12, clearedSelection=false;
 let manualIds=new Set(),selectionEpoch=0,pendingAction=null,pendingReplace=null,replaceFocus=null;
 let playbackFromPlaylist=false,undoTimer=null;
 let starTransform=d3.zoomIdentity;
 const byId = () => new Map(data.tracks.map(t=>[t.id,t]));
 const emit = (action, anchor=null) => {
  if(busy) return;
  busy=true;root.classList.add('busy');
  lastToken=Math.max(Date.now(),lastToken+1);
  pendingAction={token:lastToken,kind:action.kind,epoch:selectionEpoch,manual:manualIds.size>0,ids:action.ids||[action.id].filter(Boolean)};
  pendingFlight=anchor?{token:lastToken,rect:anchor.getBoundingClientRect(),label:action.source?.label||byId().get(action.id)?.title||'音乐已加入',group:action.kind==='add_group'||action.kind==='create'||action.kind==='query'}:null;
  root.querySelectorAll('.mutation-control').forEach(b=>b.disabled=true);
  root.querySelector('.message').textContent = action.kind==='query' ? '正在理解你的描述…' : action.kind==='export_zip'?'正在打包真实音频，转换其他格式时可能需要一些时间…':'正在处理…';
  if(action.kind==='export_zip'){const status=root.querySelector('.zip-export-status');status.hidden=false;status.textContent='正在生成 MP3 音乐包，请稍候…';}
  send('action',{...action,token:lastToken});
 };
 root.innerHTML = `
 <header class="topbar"><div class="brand"><span class="brand-mark" aria-hidden="true"><i></i></span>曲境<small>MUSEFOLDERS</small></div><div class="top-actions"><span class="library-count"></span><button data-do="all">我的收藏</button><button data-do="manage">${icon('settings')}管理曲境</button></div></header>
 <div class="section-heading"><div><span class="collection-kicker">PRIVATE COLLECTION / 我的音乐收藏</span><h2>让扁平的歌单，<span>成为立体的世界</span></h2><p>沿着声音出发，遇见一首此刻想听的歌。</p></div><div class="edition-note"><span class="edition-dot"></span>每一首，都有来处<small>你的收藏，就是探索的起点</small></div></div>
 <div class="explore"><section class="atlas" aria-label="探索音乐收藏"><nav class="tabs" role="tablist" aria-label="探索方式"><button role="tab" data-tab="map">音乐星球</button><button role="tab" data-tab="sound">听感空间</button><button role="tab" data-tab="themes">主题河流</button></nav><div class="stage" role="tabpanel"></div><div class="atlas-caption"></div></section></div>
 <section class="composer" aria-label="找歌与整理歌单"><div class="composer-head"><h2>想听什么？</h2><span class="ai-status"></span></div><form class="query-form">${icon('search')}<input name="query" aria-label="描述想听的歌曲或歌单操作" maxlength="500" placeholder="找一些睡前听的歌，或把搜索结果建成预备歌单" autocomplete="off"><button class="green-button" type="submit">找歌 ${icon('arrow')}</button></form><div class="suggestions"><button data-query="关于爱情的歌">关于爱情的歌</button><button data-query="睡前听的歌">睡前听的歌</button><button data-query="运动时听的歌">运动时听的歌</button><button data-do="new-results">把结果建成预备歌单</button></div><div class="message" aria-live="polite" role="status"></div></section>
 <div class="lower"><section class="results" aria-label="歌曲列表"><div class="results-top"><h2 class="results-title"></h2><div class="results-actions"><button data-do="play-results">${icon('play')}播放</button><button data-do="add-results">${icon('plus')}加入歌单</button><button data-do="all">全部收藏</button></div></div><div class="table-head"><span>#</span><span>歌曲 / 歌手</span><span class="album-heading">专辑</span><span>时长</span><span></span></div><div class="song-list"></div><button class="more" data-do="more">显示更多歌曲</button></section>
 <aside class="playlist"><div class="playlist-top"><button class="playlist-name" data-do="rename" title="修改预备歌单名称"></button><button class="icon-button" data-do="rename" aria-label="修改预备歌单名称">${icon('edit')}</button></div><div class="playlist-count"></div><div class="name-editor" hidden><form class="name-form"><input class="rename-input" maxlength="60" aria-label="预备歌单名称" placeholder="预备歌单名称"><div class="playlist-tools"><button class="green-button" type="submit">保存</button><button class="outline-button" type="button" data-do="cancel-name">取消</button></div></form></div><select class="saved-playlists" aria-label="打开已保存的预备歌单" hidden></select><div class="playlist-tools"><button class="outline-button" data-do="new">${icon('plus')}新建</button><button class="outline-button" data-do="export">${icon('download')}导出</button><button class="outline-button" data-do="play-playlist">${icon('play')}播放</button></div><div class="playlist-list"></div></aside></div>
 <p class="notice">画像依据收藏曲库 · 星座是声音分布的趣味表达 · 歌单保存在本机</p>
 <footer class="player" aria-label="音乐播放器"><div class="now-playing"><div class="record">${icon('music')}</div><div class="song-main"><div class="song-name now-title">选择一首收藏</div><p class="song-meta now-artist">选中歌曲后，点击播放按钮试听</p></div></div><audio controls preload="metadata" hidden aria-label="当前歌曲播放控制"></audio><div class="player-empty">好歌一直都在，随时再听一遍</div><div class="play-switch"><button class="icon-button" data-do="previous" aria-label="上一首">${icon('previous')}</button><button class="icon-button" data-do="next" aria-label="下一首">${icon('next')}</button></div></footer>`;
 // Keep exploration and its songs together, with a persistent music sidebar.
 const layout=document.createElement('main');layout.className='workspace-layout';
 const exploration=root.querySelector('.explore');
 exploration.before(layout);layout.append(exploration);
 const sidebar=document.createElement('aside');sidebar.className='music-sidebar';sidebar.setAttribute('aria-label','找歌与歌单');
 layout.append(sidebar);sidebar.append(root.querySelector('.composer'));
 const musicTabs=document.createElement('nav');musicTabs.className='music-tabs';musicTabs.setAttribute('aria-label','音乐区');
 musicTabs.innerHTML='<button data-music-view="all" aria-pressed="true">全库歌单</button><button data-music-view="selected" aria-pressed="false">选中歌曲</button>';
 sidebar.append(musicTabs,root.querySelector('.lower'));
 root.insertAdjacentHTML('beforeend',`<button class="prep-launcher" data-do="drawer-toggle" aria-label="打开我的预备歌单" aria-expanded="false"><span class="prep-discs" aria-hidden="true">${icon('music')}</span><span>我的预备歌单<small class="prep-badge">0 首</small></span></button><div class="prep-backdrop" data-do="drawer-close" hidden></div><section class="prep-drawer" role="dialog" aria-modal="true" aria-label="我的预备歌单" hidden><header class="prep-header"><div><span class="prep-kicker">PREPARATION / 唱片盒</span><h2>我的预备歌单</h2></div><button class="icon-button" data-do="drawer-close" aria-label="关闭我的预备歌单">${icon('close')}</button></header><p class="prep-explanation">板块完整保留，单曲独立挑选，导出自动去重。</p><div class="prep-body"></div></section><span class="prep-status sr-only" role="status" aria-live="polite"></span>`);
 root.querySelector('.prep-body').append(root.querySelector('.playlist'));
 root.querySelector('.prep-explanation').textContent='整批加入，逐曲整理；每首保留加入来源。';
 root.querySelector('.prep-header').insertAdjacentHTML('beforeend',`<button class="icon-button" data-do="reset-ball" aria-label="重置悬浮球位置">${icon('reset')}</button>`);
 root.querySelector('.playlist > .playlist-tools').insertAdjacentHTML('beforeend','<button class="outline-button mutation-control" data-do="undo-delete" hidden>撤销删除</button>');
 root.querySelector('.playlist > .playlist-tools').insertAdjacentHTML('beforeend','<button class="outline-button mutation-control" data-do="clear-playlist">清空歌单</button>');
 const exportButton=root.querySelector('[data-do="export"]');
 exportButton.innerHTML=icon('download')+'导出M3U8';
 exportButton.className='green-button mutation-control';
 exportButton.insertAdjacentHTML('afterend',`<button class="outline-button mutation-control" data-do="export-zip">${icon('download')}导出音乐ZIP</button>`);
 root.querySelector('.playlist-list').insertAdjacentHTML('beforebegin','<p class="export-guidance selection-detail"></p>');
 root.querySelector('.playlist-list').insertAdjacentHTML('beforebegin','<p class="zip-export-status selection-detail" role="status" aria-live="polite" hidden></p>');
 root.insertAdjacentHTML('beforeend','<div class="cover-overlay" hidden><section class="cover-dialog" role="alertdialog" aria-modal="true" aria-labelledby="cover-title"><h2 id="cover-title">选择可能被覆盖</h2><p class="cover-description"></p><button data-do="cancel-replace">返回继续选择</button><button class="green-button" data-do="confirm-replace">继续探索</button></section></div>');
 let musicView='all', drawerReturnFocus=null;
 function showMusic(view){musicView=view==='results'?'selected':view;musicTabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.musicView===musicView)));renderRows();}
 function setDrawer(open){const wasOpen=drawerOpen;drawerOpen=open;root.querySelector('.prep-drawer').hidden=!open;root.querySelector('.prep-backdrop').hidden=!open;root.querySelector('.prep-launcher').setAttribute('aria-expanded',String(open));if(open){if(!wasOpen)drawerReturnFocus=root.getRootNode().activeElement;root.querySelector('button[data-do="drawer-close"]').focus();}else if(drawerReturnFocus?.isConnected)drawerReturnFocus.focus();else root.querySelector('.prep-launcher').focus();}
 function revealMusic(){if(matchMedia('(max-width: 760px)').matches)sidebar.scrollIntoView({block:'start',behavior:'smooth'});}
 const audio=root.querySelector('audio');
 const ball=root.querySelector('.prep-launcher');let ballPosition=null,dragBall=null,suppressBallClick=false;
 try{ballPosition=JSON.parse(localStorage.getItem('musefolders-prep-position'));}catch(error){ballPosition=null;}
 function placeBall(){const p=root.querySelector('.player').getBoundingClientRect(),b=ball.getBoundingClientRect();const width=window.innerWidth,height=window.innerHeight;const maxX=Math.max(12,width-b.width-12),maxY=Math.max(12,Math.min(height-12,p.top-18)-b.height);const candidate=ballPosition&&Number.isFinite(ballPosition.x)&&Number.isFinite(ballPosition.y)?ballPosition:{x:20,y:maxY};const x=Math.max(12,Math.min(maxX,candidate.x)),y=Math.max(12,Math.min(maxY,candidate.y));Object.assign(ball.style,{left:x+'px',top:y+'px',bottom:'auto'});if(ballPosition)ballPosition={x,y};}
 function storeBall(){try{if(ballPosition)localStorage.setItem('musefolders-prep-position',JSON.stringify(ballPosition));else localStorage.removeItem('musefolders-prep-position');}catch(error){root.querySelector('.prep-status').textContent='当前位置仅在本次访问保留。';}}
 ball.addEventListener('pointerdown',e=>{if(e.button!==0)return;const rect=ball.getBoundingClientRect();dragBall={id:e.pointerId,x:e.clientX,y:e.clientY,left:rect.left,top:rect.top,moved:false};ball.setPointerCapture(e.pointerId);});
 function moveBall(e){if(!dragBall||e.pointerId!==dragBall.id)return;const dx=e.clientX-dragBall.x,dy=e.clientY-dragBall.y;if(Math.hypot(dx,dy)>6)dragBall.moved=true;if(dragBall.moved){ballPosition={x:dragBall.left+dx,y:dragBall.top+dy};placeBall();}}
 function endBall(e){if(!dragBall||e.pointerId!==dragBall.id)return;if(e.type==='pointerup')moveBall(e);suppressBallClick=dragBall.moved;dragBall=null;storeBall();setTimeout(()=>suppressBallClick=false,0);}
 root.ownerDocument.addEventListener('pointermove',moveBall);
 root.ownerDocument.addEventListener('pointerup',endBall);root.ownerDocument.addEventListener('pointercancel',endBall);
 ball.addEventListener('keydown',e=>{if(e.key==='Home'){e.preventDefault();ballPosition=null;placeBall();storeBall();return;}if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const rect=ball.getBoundingClientRect();ballPosition={x:rect.left+(e.key==='ArrowLeft'?-20:e.key==='ArrowRight'?20:0),y:rect.top+(e.key==='ArrowUp'?-20:e.key==='ArrowDown'?20:0)};placeBall();storeBall();});
 const playerObserver=new ResizeObserver(()=>{if(!root.isConnected){playerObserver.disconnect();window.removeEventListener('resize',placeBall);root.ownerDocument.removeEventListener('pointermove',moveBall);root.ownerDocument.removeEventListener('pointerup',endBall);root.ownerDocument.removeEventListener('pointercancel',endBall);return;}const height=root.querySelector('.player').getBoundingClientRect().height;root.style.setProperty('--prep-offset',Math.ceil(height+18)+'px');placeBall();});
 playerObserver.observe(root.querySelector('.player'));
 window.addEventListener('resize',placeBall);
 let naming='rename';
 function selection(){
  const ids=byId();
  if(manualIds.size)return [...manualIds].map(id=>ids.get(id)).filter(Boolean);
  if(focusedId) return [ids.get(focusedId)].filter(Boolean);
  if(replayEntry) return replayEntry.ids.map(id=>ids.get(id)).filter(Boolean);
  if(filter) return filter.ids.map(id=>ids.get(id)).filter(Boolean);
  if(data.results&&!clearedSelection) return data.results.hits.map(h=>ids.get(h.id)).filter(Boolean);
  return [];
 }
 function visible(){return musicView==='all'?data.tracks.filter(t=>t.analyzed):selection();}
 function resetFocus(){focusedId=null;replayEntry=null;selectionCount=12;}
 function clearCurrent(){manualIds.clear();resetFocus();filter=null;starBounds=null;clearedSelection=true;selectionEpoch++;}
 function replaceSelection(change){const commit=()=>{clearCurrent();change();};if(manualIds.size){pendingReplace=commit;replaceFocus=root.getRootNode().activeElement;root.querySelector('.cover-description').textContent=`当前有 ${manualIds.size} 首待加入歌曲，继续探索可能覆盖这些选择。`;root.querySelector('.cover-overlay').hidden=false;root.querySelector('[data-do="cancel-replace"]').focus();return;}commit();}
 function closeReplace(confirm){const change=pendingReplace;pendingReplace=null;root.querySelector('.cover-overlay').hidden=true;if(replaceFocus?.isConnected)replaceFocus.focus();if(confirm&&change)change();else{renderStage();renderRows();}}
 function sourceOfSelection(){
  if(manualIds.size)return {kind:'selection',key:'library-manual',label:'全库手选',description:'从全库手动挑选',criteria:{manual:true}};
  if(replayEntry)return replayEntry.source;
  if(filter?.country)return {kind:'country',key:filter.country,label:filter.label,description:'首位署名艺人关联地区 · '+filter.label,criteria:{country:filter.country}};
  if(filter?.kind==='energy'||filter?.kind==='themes'){const g=(filter.kind==='energy'?atmospheres:stories)[filter.scene];return {kind:filter.kind,key:g.name,label:g.name,description:g.note,criteria:{scene:filter.scene}};}
  if(filter?.kind==='star')return {kind:'star',key:JSON.stringify(filter.bounds),label:'星图框选',description:'节奏与明亮度选区',criteria:{bounds:filter.bounds}};
  if(filter)return {kind:'selection',key:filter.label,label:filter.label,description:'探索选择快照',criteria:{}};
  if(data.results&&!clearedSelection)return {kind:'search',key:data.results.query,label:data.results.query.slice(0,100),description:(data.conditions||[]).join(' · ')||'搜索结果快照',criteria:{query:data.results.query}};
  return null;
 }
 function describeSource(source){
  const bounds=source?.criteria?.bounds;
  if(source?.kind==='star'&&Array.isArray(bounds)&&bounds.length===2&&bounds.every(row=>Array.isArray(row)&&row.length===2&&row.every(Number.isFinite)))return `节奏指数 ${bounds[0][0].toFixed(1)}–${bounds[1][0].toFixed(1)} · 明亮度 ${bounds[0][1].toFixed(1)}–${bounds[1][1].toFixed(1)}`;
  return source?.description||'加入时的完整快照';
 }
 function visibleSource(){return musicView==='all'?{kind:'library',key:'all-analyzed',label:'全库歌单',description:'已导入并成功分析的歌曲',criteria:{analyzed:true}}:sourceOfSelection();}
 function focusSong(id){if(!byId().has(id))return;replaceSelection(()=>{focusedId=id;showMusic('selected');renderStage();revealMusic();});}
 function setFilter(label,tracks){replaceSelection(()=>{filter={label,ids:tracks.map(t=>t.id)};showMusic('selected');renderStage();revealMusic();});}
 function showName(mode){setDrawer(true);naming=mode;root.querySelector('.name-editor').hidden=false;const input=root.querySelector('.rename-input');input.value=mode==='rename'?data.playlist.name:'';input.placeholder=mode==='rename'?'预备歌单名称':'给新预备歌单起个名字';input.focus();}
 function animateAdded(flight){
  const target=root.querySelector('.prep-launcher');root.querySelector('.prep-status').textContent=(flight.group?'板块':'单曲')+'已加入我的预备歌单';
  target.classList.remove('prep-confirmed');void target.offsetWidth;target.classList.add('prep-confirmed');
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const end=target.getBoundingClientRect(),r=flight.rect;
  const item=document.createElement('div');item.className='prep-flight '+(flight.group?'group-flight':'');item.textContent=flight.label;item.setAttribute('aria-hidden','true');
  Object.assign(item.style,{left:r.left+'px',top:r.top+'px'});root.append(item);
  const dx=end.left+end.width/2-r.left,dy=end.top+end.height/2-r.top;
  item.animate([{transform:'translate(0,0) scale(1)',opacity:1},{transform:`translate(${dx*.5}px,${dy*.5-65}px) scale(.8)`,opacity:.9},{transform:`translate(${dx}px,${dy}px) scale(.2)`,opacity:0}],{duration:650,easing:'cubic-bezier(.3,.1,.4,1)'}).finished.finally(()=>item.remove());
 }
 function drawStar(svg,mini=false){
  const side=mini?260:560,margin=mini?{l:8,r:8,t:8,b:8}:{l:58,r:20,t:22,b:54};
  const plot=side-margin.l-margin.r,height=plot+margin.t+margin.b;
  const extent=[[margin.l,margin.t],[margin.l+plot,margin.t+plot]];
  const s=d3.select(svg).attr('viewBox',`0 0 ${side} ${height}`);s.selectAll('*').remove();
  const baseX=d3.scaleLinear().domain([0,100]).range([margin.l,margin.l+plot]);
  const baseY=d3.scaleLinear().domain([0,100]).range([margin.t+plot,margin.t]);
  let x=mini?baseX:starTransform.rescaleX(baseX),y=mini?baseY:starTransform.rescaleY(baseY);
  const clipId=svg.dataset.starClip||(svg.dataset.starClip='star-clip-'+Math.random().toString(36).slice(2));
  s.append('defs').append('clipPath').attr('id',clipId).append('rect').attr('x',margin.l).attr('y',margin.t).attr('width',plot).attr('height',plot);
  const chart=s.append('g').attr('clip-path',`url(#${clipId})`),grid=chart.append('g');
  const xLabels=s.append('g'),yLabels=s.append('g');
  if(!mini){s.append('text').attr('x',margin.l+plot/2).attr('y',height-5).attr('text-anchor','middle').attr('fill','#b3c5b8').attr('font-size',12).text('节奏指数 · 慢 → 快');s.append('text').attr('transform',`translate(16,${margin.t+plot/2}) rotate(-90)`).attr('text-anchor','middle').attr('fill','#b3c5b8').attr('font-size',12).text('明亮度 · 暗 → 亮');}
  const edges=chart.selectAll('.star-edge').data(showConstellation?data.star.edges:[]).join('line').attr('class','star-edge').attr('stroke','#82ac8e').attr('stroke-width',mini?1.3:1.8).attr('opacity',.8);
  const stars=chart.selectAll('.constellation-dot').data(showConstellation?data.star.nodes:[]).join('circle').attr('class','constellation-dot').attr('r',mini?2:3).attr('fill','#9dccaa');
  const color=d3.scaleLinear().domain([0,50,100]).range(['#87a9df','#b7c8bf','#e9a76d']);
  const dots=chart.selectAll('.plot-dot').data(data.tracks.filter(t=>t.x!==null)).join('circle').attr('class','plot-dot').attr('r',mini?3:5.8).attr('fill',t=>color(t.activity??50)).attr('opacity',.86);
  dots.append('title').text(t=>`${t.title} · ${t.artist}`);
  let brush=null,layer=null;
  function paintSelection(){const linked=filter?.kind==='star'||filter?.kind==='energy',selected=new Set(linked?filter.ids:[]);dots.classed('selected',t=>selected.has(t.id)).attr('opacity',t=>linked&&!selected.has(t.id)?.24:.9);const status=root.querySelector('.star-selection');if(status)status.textContent=filter?.kind==='star'?`已选 ${selected.size} 首 · 在歌曲列表试听或加入预备歌单`:filter?.kind==='energy'?`${filter.label} · 高亮 ${selected.size} 首`:'在图中空白处拖动框选，或点击歌曲圆点选中';const clear=root.querySelector('[data-do="clear-star"]');if(clear)clear.disabled=!linked;}
  function paint(){
   const original=mini||Math.abs(starTransform.k-1)<1e-6;
   const xticks=original?[0,25,50,75,100]:x.ticks(5).filter(t=>t>=0&&t<=100),yticks=original?[0,25,50,75,100]:y.ticks(5).filter(t=>t>=0&&t<=100);
   grid.selectAll('*').remove();
   for(const t of xticks)grid.append('line').attr('x1',x(t)).attr('x2',x(t)).attr('y1',margin.t).attr('y2',margin.t+plot).attr('stroke','#2e3c33').attr('stroke-width',.7);
   for(const t of yticks)grid.append('line').attr('y1',y(t)).attr('y2',y(t)).attr('x1',margin.l).attr('x2',margin.l+plot).attr('stroke','#2e3c33').attr('stroke-width',.7);
   if(!mini){xLabels.selectAll('text').data(xticks).join('text').attr('x',x).attr('y',margin.t+plot+22).attr('text-anchor','middle').attr('fill','#a4b6a9').attr('font-size',11).text(t=>t);yLabels.selectAll('text').data(yticks).join('text').attr('x',margin.l-12).attr('y',t=>y(t)+4).attr('text-anchor','end').attr('fill','#a4b6a9').attr('font-size',11).text(t=>t);}
   edges.attr('x1',e=>x(data.star.nodes[e[0]][0])).attr('y1',e=>y(data.star.nodes[e[0]][1])).attr('x2',e=>x(data.star.nodes[e[1]][0])).attr('y2',e=>y(data.star.nodes[e[1]][1]));
   stars.attr('cx',p=>x(p[0])).attr('cy',p=>y(p[1]));
   dots.attr('cx',t=>x(t.x)).attr('cy',t=>y(t.y)).attr('display',t=>x(t.x)>=margin.l&&x(t.x)<=margin.l+plot&&y(t.y)>=margin.t&&y(t.y)<=margin.t+plot?null:'none');
   if(layer){
    const bounds=filter?.kind==='star'?filter.bounds:null;
    if(bounds){const a=[Math.max(margin.l,x(bounds[0][0])),Math.max(margin.t,y(bounds[1][1]))],b=[Math.min(margin.l+plot,x(bounds[1][0])),Math.min(margin.t+plot,y(bounds[0][1]))];starBounds=a[0]<b[0]&&a[1]<b[1]?[a,b]:null;}else starBounds=null;
    layer.call(brush.move,starBounds);
   }
   if(!mini){svg.dataset.zoom=starTransform.k.toFixed(3);svg.dataset.xDomain=x.domain().join(',');svg.dataset.yDomain=y.domain().join(',');const label=root.querySelector('.star-zoom-level');if(label)label.textContent=starTransform.k.toFixed(1)+'×';root.querySelector('[data-do="star-zoom-in"]').disabled=starTransform.k>=12-1e-6;root.querySelector('[data-do="star-zoom-out"]').disabled=starTransform.k<=1+1e-6;paintSelection();}
  }
  if(!mini){
   brush=d3.brush().extent(extent).filter(e=>!e.shiftKey&&!e.ctrlKey&&!e.button).on('end',e=>{
    if(!e.sourceEvent)return;
    const rectangle=e.selection;
    replaceSelection(()=>{musicView='selected';starBounds=rectangle;
     if(rectangle){const [[x0,y0],[x1,y1]]=rectangle,chosen=data.tracks.filter(t=>t.x!==null&&x(t.x)>=x0&&x(t.x)<=x1&&y(t.y)>=y0&&y(t.y)<=y1);filter={label:'星图选中的歌曲',ids:chosen.map(t=>t.id),kind:'star',bounds:[[+x.invert(x0).toFixed(3),+y.invert(y1).toFixed(3)],[+x.invert(x1).toFixed(3),+y.invert(y0).toFixed(3)]]};}
     paint();landscape('energy',root.querySelector('.sound-map'));renderRows();
    });
   });
   layer=chart.insert('g','.plot-dot').attr('class','star-brush').call(brush);layer.select('.overlay').attr('aria-label','拖动框选星图中的歌曲');
   const navigation=d3.zoom().extent(extent).translateExtent(extent).scaleExtent([1,12]).wheelDelta(e=>Math.max(-.5,Math.min(.5,-e.deltaY*(e.deltaMode===1?.05:e.deltaMode?.1:.002)))).filter(e=>e.type==='wheel'?e.ctrlKey:e.type==='mousedown'&&e.shiftKey&&!e.button).on('zoom',e=>{starTransform=e.transform;x=starTransform.rescaleX(baseX);y=starTransform.rescaleY(baseY);paint();});
   s.call(navigation).call(navigation.transform,starTransform);
   root._starView={zoom:factor=>s.call(navigation.scaleBy,factor),reset:()=>s.call(navigation.transform,d3.zoomIdentity),pan:(dx,dy)=>s.call(navigation.translateBy,dx/starTransform.k,dy/starTransform.k)};
   svg.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();clearCurrent();paint();landscape('energy',root.querySelector('.sound-map'));renderRows();}else if(['+','=','-','_','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='0')root._starView.reset();else if(['+','='].includes(e.key))root._starView.zoom(1.4);else if(['-','_'].includes(e.key))root._starView.zoom(1/1.4);else root._starView.pan(e.key==='ArrowLeft'?60:e.key==='ArrowRight'?-60:0,e.key==='ArrowUp'?60:e.key==='ArrowDown'?-60:0);}};
   dots.attr('tabindex',0).attr('role','button').attr('aria-label',t=>`选中 ${t.title}`).on('click',(e,t)=>{if(!e.defaultPrevented)focusSong(t.id);}).on('keydown',(e,t)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focusSong(t.id);}});
  }
  paint();
 }
 function drawGlobe(){
  const stage=root.querySelector('.stage');stage.innerHTML=`<div class="globe-layout"><div><svg class="globe" tabindex="0" role="img" aria-label="可旋转的音乐地球，滚轮缩放，方向键旋转，点击国家查看歌曲"></svg><div class="globe-tools"><button class="icon-button" data-do="zoom-out" aria-label="缩小地球">${icon('minus')}</button><button class="icon-button" data-do="reset-globe" aria-label="重置地球">${icon('reset')}</button><span class="zoom-label" aria-label="地球缩放倍数"></span><button class="icon-button" data-do="zoom-in" aria-label="放大地球">${icon('plus')}</button></div></div><div class="region-list"></div></div>`;
  const svg=stage.querySelector('.globe'),s=d3.select(svg).attr('viewBox','0 0 510 390');
  const projection=d3.geoOrthographic().translate([255,190]).scale(172*zoom).rotate(rotation).clipAngle(90),path=d3.geoPath(projection);
  const available = new Map();data.tracks.forEach(t=>{if(t.country)available.set(t.country,(available.get(t.country)||0)+1)});
  const locations=(data.regions?.length?data.regions:countries).map(c=>{
   const feature=world.features.find(f=>String(f.id).padStart(3,'0')===c.id);
   return {...c,center:c.center||(feature?d3.geoCentroid(feature):[0,0])};
  }).sort((a,b)=>(available.get(b.id)||0)-(available.get(a.id)||0));
  s.append('path').datum({type:'Sphere'}).attr('class','sphere').attr('fill','#14221a').attr('stroke','#5d8069').attr('stroke-width',1);
  s.append('path').datum(d3.geoGraticule10()).attr('class','graticule').attr('fill','none').attr('stroke','#33533d').attr('stroke-width',.55);
  s.selectAll('.country').data(world.features.filter(f=>f.id!=='010')).join('path').attr('class','country').attr('fill',f=>available.has(String(f.id).padStart(3,'0'))?'#558b62':'#2e4c36').attr('stroke','#102b1c').attr('stroke-width',.65).on('click',(e,f)=>{
   if(e.defaultPrevented)return;const id=String(f.id).padStart(3,'0'),label=locations.find(c=>c.id===id)?.name||countries.find(c=>c.id===id)?.name||f.properties?.name||'选中地区';chooseRegion(id,label,d3.geoCentroid(f));
  }).append('title').text(f=>`${locations.find(c=>c.id===String(f.id).padStart(3,'0'))?.name||countries.find(c=>c.id===String(f.id).padStart(3,'0'))?.name||f.properties?.name||'地区'} · ${available.get(String(f.id).padStart(3,'0'))||0} 首`);
  const markers=s.selectAll('.region-marker').data(locations.filter(c=>available.has(c.id))).join('g').attr('class','region-marker').attr('role','button').attr('tabindex',0).attr('aria-label',c=>`${c.name} ${available.get(c.id)}首`).on('click',(e,c)=>{if(!e.defaultPrevented)chooseRegion(c.id,c.name,c.center)}).on('keydown',(e,c)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();chooseRegion(c.id,c.name,c.center);}});
  markers.append('circle').attr('r',13).attr('fill','transparent');markers.append('circle').attr('r',4).attr('fill','#75e4a3').attr('stroke','#11291b').attr('stroke-width',1.5);
  markers.append('text').attr('x',9).attr('y',-7).attr('fill','#e4ffec').attr('font-size',11).attr('paint-order','stroke').attr('stroke','#10251a').attr('stroke-width',3).text(c=>`${c.name} ${available.get(c.id)}`);
  markers.append('title').text(c=>`${c.name} · ${available.get(c.id)} 首`);
  function paint(){projection.rotate(rotation).scale(172*zoom);svg.dataset.zoom=zoom.toFixed(3);svg.dataset.rotation=rotation.join(',');stage.querySelector('.zoom-label').textContent=`${zoom.toFixed(1)}×`;s.selectAll('path').attr('d',path);s.selectAll('.country').classed('region-active',f=>filter?.country===String(f.id).padStart(3,'0'));const center=projection.invert([255,190]);markers.attr('display',c=>d3.geoDistance(center,c.center)<Math.PI/2-.05?null:'none').attr('transform',c=>`translate(${projection(c.center).join(',')})`);const occupied=[];const ordered=locations.filter(c=>available.has(c.id)).sort((a,b)=>(b.id===filter?.country)-(a.id===filter?.country));for(const c of ordered){const label=markers.filter(p=>p.id===c.id).select('text'),[px,py]=projection(c.center),rect=[px+7,py-19,px+15+c.name.length*11+String(available.get(c.id)).length*7,py-3],front=d3.geoDistance(center,c.center)<Math.PI/2-.05;const collision=occupied.some(r=>rect[0]<r[2]+4&&rect[2]>r[0]-4&&rect[1]<r[3]+3&&rect[3]>r[1]-3);const show=front&&!collision&&rect[0]>=0&&rect[2]<505&&rect[1]>=0&&rect[3]<390;label.attr('display',show?null:'none');if(show)occupied.push(rect);}}
  function chooseRegion(id,name,center){replaceSelection(()=>{musicView='selected';rotation=[-center[0],-center[1],0];paint();filter={label:name,ids:data.tracks.filter(t=>t.country===id).map(t=>t.id),country:id};paint();showMusic('selected');renderRegions();revealMusic();});}
  function renderRegions(){
   const unknown=data.tracks.filter(t=>!t.country).length;
   stage.querySelector('.region-list').innerHTML=`<div class="region-summary">${available.size} 个地区 · ${data.tracks.length-unknown} 首</div><div class="region-buttons">`+locations.map(c=>`<button data-region="${esc(c.id)}" class="${filter?.country===c.id?'active':''}"><span>${esc(c.name)}</span><small>${available.get(c.id)||0}</small></button>`).join('')+`</div><button data-do="unknown-region"><span>待补充</span><small>${unknown}</small></button><div class="region-note">按首位署名艺人关联地区<br>拖动旋转 · 滚轮缩放</div>`;
   stage.querySelectorAll('[data-region]').forEach(b=>b.onclick=()=>{const c=locations.find(c=>c.id===b.dataset.region);chooseRegion(c.id,c.name,c.center);});
  }
  s.call(d3.drag().on('start',e=>{svg._rot=[...rotation];svg._drag=[e.x,e.y];}).on('drag',e=>{rotation=[svg._rot[0]+(e.x-svg._drag[0])*.35,Math.max(-75,Math.min(75,svg._rot[1]-(e.y-svg._drag[1])*.35)),0];paint();}));
  svg.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();rotation[0]+=e.key==='ArrowLeft'?-12:e.key==='ArrowRight'?12:0;rotation[1]=Math.max(-75,Math.min(75,rotation[1]+(e.key==='ArrowUp'?8:e.key==='ArrowDown'?-8:0)));paint();};
  svg.addEventListener('wheel',e=>{e.preventDefault();const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?390:1);zoom=Math.max(.7,Math.min(4,zoom*Math.exp(-Math.max(-500,Math.min(500,delta))*.002)));paint();},{passive:false});
  root._globePaint=paint;paint();renderRegions();
 }
 // Places are artistic representations of measured audio groups, not inferred geography.
 const atmospheres=[
  {name:'晨光林地',note:'起伏较缓 · 音色明亮',x:24,y:37,px:27,py:51,p:t=>t.activity<50&&t.y>=50},
  {name:'旷野来风',note:'声音活跃 · 音色明亮',x:75,y:28,px:73,py:44,p:t=>t.activity>=50&&t.y>=50},
  {name:'静谧湖畔',note:'起伏较缓 · 音色偏暗',x:23,y:62,px:29,py:77,p:t=>t.activity<50&&t.y<50},
  {name:'深谷回响',note:'声音活跃 · 音色偏暗',x:74,y:70,px:70,py:85,p:t=>t.activity>=50&&t.y<50}
 ];
 const measured=()=>data.tracks.filter(t=>Number.isFinite(t.activity)&&Number.isFinite(t.y));
 const stories=[
  {name:'爱情',note:'把爱唱给你听',x:17,y:29,px:24,py:40,mx:18,my:34},
  {name:'暗恋',note:'还没说出口的喜欢',x:46,y:31,px:47,py:42,mx:51,my:34},
  {name:'思念',note:'想见的人，在歌里',x:14,y:50,px:24,py:61,mx:15,my:55},
  {name:'失恋',note:'那些告别之后',x:81,y:82,px:70,py:88,mx:83,my:80},
  {name:'成长',note:'慢慢成为自己',x:81,y:34,px:74,py:43,mx:83,my:34},
  {name:'回忆',note:'留住过去的片刻',x:47,y:53,px:48,py:66,mx:48,my:57},
  {name:'孤独',note:'一个人的心事',x:80,y:57,px:73,py:70,mx:81,my:60},
  {name:'友情',note:'一起走过的日子',x:18,y:77,px:29,py:87,mx:18,my:78},
  {name:'亲情',note:'写给家人的歌',x:56,y:81,px:54,py:91,mx:51,my:80}
 ];
 function sceneSongs(group,kind){return kind==='energy'?measured().filter(group.p):data.tracks.filter(t=>t.themes.includes(group.name));}
 function chooseScene(index,kind){replaceSelection(()=>{musicView='selected';
  const group=(kind==='energy'?atmospheres:stories)[index];
  if(!group)return;
  starBounds=null;filter={label:group.name,ids:sceneSongs(group,kind).map(t=>t.id),kind,scene:index};count=12;
  renderStage();showMusic('selected');revealMusic();});
 }
 function landscape(kind,target=root.querySelector('.stage')){
  const energy=kind==='energy',groups=energy?atmospheres:stories;
  const active=filter?.kind===kind?groups[filter.scene]:null;
  const selected=active?sceneSongs(active,kind):[];
  const labels=groups.map((group,index)=>{
   const songs=sceneSongs(group,kind);
   return `<button class="landmark ${!songs.length?'uninhabited':''} ${active===group?'selected':''}" data-scene="${index}" data-scene-kind="${kind}" style="--x:${group.x}%;--y:${group.y}%;--mobile-x:${group.mx??group.x}%;--mobile-y:${group.my??group.y}%" aria-pressed="${active===group}" aria-label="${group.name}，${songs.length} 首，${group.note}"><strong>${group.name}</strong><span>${songs.length} 首 <i>· ${group.note}</i></span></button>`;
  }).join('');
  const regionShapes=[
   'M3 18C17 8 36 9 46 25S44 43 31 46S10 43 3 36Z',
   'M53 18C72 12 97 20 97 39S87 56 72 53S52 43 53 18Z',
   'M4 46C16 40 41 47 45 60S43 90 22 94S3 78 4 46Z',
   'M56 52C69 49 92 52 97 69S89 96 72 95S48 77 56 52Z'
  ];
  const regions=energy?`<svg class="landscape-regions" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${regionShapes.map((path,index)=>`<path d="${path}" data-region-scene="${index}" class="${filter?.kind===kind&&filter.scene===index?'selected':''}"/>`).join('')}</svg>`:'';
  const lights=groups.map((group,index)=>{
   const songs=sceneSongs(group,kind).slice().sort((a,b)=>a.id.localeCompare(b.id));
   // Keep the scenery readable; every place still includes all matching songs.
   return songs.slice(0,energy?9:2).map((song,i)=>{
    const angle=i*2.39996,indexRadius=Math.sqrt(i+1),x=group.px+Math.cos(angle)*indexRadius*(energy?3.8:3),y=group.py+Math.sin(angle)*indexRadius*(energy?2.8:2),mx=(group.mx??group.px)+(energy?0:5)+Math.cos(angle)*indexRadius*(energy?3.8:3),my=(energy?group.py:Math.min(90,group.my+10))+Math.sin(angle)*indexRadius*(energy?2.8:2);
    return `<button class="song-light ${x<25?'tooltip-start':x>75?'tooltip-end':''} ${active&&active!==group?'dimmed':''} ${playing===song.id?'playing':''}" data-focus="${esc(song.id)}" data-scene-light="${index}" style="--x:${x}%;--y:${y}%;--mobile-x:${mx}%;--mobile-y:${my}%" aria-label="选中 ${esc(song.title)} · ${esc(song.artist)}"><span class="light-ripple"></span><span class="light-core"></span><span class="light-tooltip"><strong>${esc(song.title)}</strong><small>${esc(song.artist)}</small><em>点击选中 · 在歌曲列表试听</em></span></button>`;
   }).join('');
  }).join('');
  const title=energy?'氛围地图':'主题河流',subtitle=energy?'收藏里的声音，长成一片风景':'顺着歌词，走过收藏里的故事';
  target.innerHTML=`<section class="landscape-panel ${energy?'sound-landscape':'story-landscape'}" aria-label="${title}"><div class="landscape-canvas"><div class="landscape-art" aria-hidden="true"></div><div class="landscape-shade" aria-hidden="true"></div><div class="landscape-heading"><h3>${title}</h3><p>${subtitle}</p></div>${regions}<div class="landscape-places">${labels}</div><div class="landscape-lights">${lights}</div><div class="landscape-hint">${energy?'点击一片风景，发现其中的歌曲':'点击河畔主题，听一段收藏里的故事'}</div></div><div class="landscape-selection" aria-live="polite"><div><span class="selection-eyebrow">${active?'你正在探索':'从收藏出发'}</span><h4>${active?esc(active.name):energy?'想去哪里听听？':'沿河，遇见一段故事'} ${active?`<small>${selected.length} 首</small>`:''}</h4><p>${active?esc(active.note):'点击地点查看歌曲，点击光点选中单曲'}${active&&!selected.length?' · 收藏中暂时没有匹配歌曲':''}</p></div><div class="landscape-actions"><button class="green-button" data-do="scene-play" ${!selected.length?'disabled':''}>${icon('play')}试听</button><button class="outline-button mutation-control" data-do="scene-add" ${!selected.length?'disabled':''}>整板块加入预备歌单</button><button class="outline-button mutation-control" data-do="scene-create" ${!selected.length?'disabled':''}>创建预备歌单</button></div></div></section>`;
 }
 function renderStage(){
  root.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tab===tab)));
  const stage=root.querySelector('.stage'),caption=root.querySelector('.atlas-caption');
  if(tab==='map'){drawGlobe();stage.insertAdjacentHTML('afterbegin','<p class="view-intro">按艺人关联地区，探索收藏里的世界</p>');caption.innerHTML='<span>滚轮缩放 · 拖动旋转 · 点击地区选歌</span><span>地区资料来自艺人档案</span>';}
  if(tab==='sound'){
   stage.innerHTML='<section class="sound-space" aria-label="听感空间"><p class="view-intro">同一份收藏，上面看声音分布，下面按氛围探索。</p><section class="sound-chart" aria-label="声音星图"><div class="sound-chart-heading"><div><h3>声音星图</h3><p>每颗星是一首收藏，位置来自声音特征，可拖动框选歌曲。</p></div><details class="sound-principle"><summary>图怎么看</summary><p>横向表示节奏指数，纵向表示明亮度，颜色表示活跃度。连线是根据整库声音分布匹配的趣味星座轮廓。</p></details></div><div class="star-tools"><span class="star-selection" role="status"></span><button class="outline-button" data-do="clear-star">清除筛选</button></div><div class="star-view-tools" role="group" aria-label="声音星图视图"><button class="icon-button" data-do="star-zoom-out" aria-label="缩小声音星图" title="缩小" data-star-icon="minus"></button><span class="star-zoom-level zoom-label" aria-live="polite">1.0×</span><button class="icon-button" data-do="star-zoom-in" aria-label="放大声音星图" title="放大" data-star-icon="plus"></button><button class="icon-button" data-do="star-zoom-reset" aria-label="重置声音星图视图" title="重置视图" data-star-icon="reset"></button><button class="icon-button" data-do="star-pan-left" aria-label="向左查看星图" title="向左查看" data-star-icon="left"></button><button class="icon-button" data-do="star-pan-right" aria-label="向右查看星图" title="向右查看" data-star-icon="right"></button><button class="icon-button" data-do="star-pan-up" aria-label="向上查看星图" title="向上查看" data-star-icon="up"></button><button class="icon-button" data-do="star-pan-down" aria-label="向下查看星图" title="向下查看" data-star-icon="down"></button></div><svg class="full-star" tabindex="0" aria-label="节奏与明亮度的声音星图，可拖动框选歌曲，按 Escape 清除选区"></svg><p class="sound-legend">颜色：活跃度低 → 高 · Ctrl＋滚轮缩放 · Shift＋拖动移图</p></section><details class="constellation-option"><summary>专属星座与分享 <span>可选 · 根据收藏自动生成</span></summary><div class="constellation-content"><h3 class="star-name"></h3><p class="profile-note"></p><button class="outline-button" data-do="share">分享我的星座</button><div class="share-preview"></div></div></details><div class="sound-map"></div></section>';
   stage.querySelectorAll('[data-star-icon]').forEach(button=>button.innerHTML=icon(button.dataset.starIcon));
   const option=stage.querySelector('.constellation-option');option.open=showConstellation;
   option.ontoggle=()=>{showConstellation=option.open;drawStar(stage.querySelector('.full-star'));};
   stage.querySelector('.star-name').textContent=data.star.name;
   stage.querySelector('.profile-note').textContent=data.star.status==='matched'?`由 ${data.star.measured??data.tracks.length} 首已分析收藏的声音分布自动生成，展开时在图中显示星座轮廓。`:'需要 12 首有音频分析的不同录音，才能生成音乐星座。';
   stage.querySelector('[data-do=share]').disabled=data.star.status!=='matched';
   stage.querySelector('.share-preview').innerHTML=data.share?`<img src="${esc(data.share)}" alt="我的音乐星座分享卡"><a href="${esc(data.share)}" download="我的音乐星座.png">下载我的星座分享卡 ${icon('download')}</a>`:'';
   landscape('energy',stage.querySelector('.sound-map'));drawStar(stage.querySelector('.full-star'));
   caption.innerHTML='<span>将歌曲的活跃度与明亮度化成风景，点击地点选歌</span><span>地点包含全部匹配歌曲</span>';
  }
  if(tab==='themes'){landscape('themes');stage.insertAdjacentHTML('afterbegin','<p class="view-intro">从歌词中提取主题，沿着河流发现相似的故事</p>');const tagged=data.tracks.filter(t=>t.themes.length).length;caption.innerHTML=`<span>一首歌可以流经多个故事 · ${data.tracks.length-tagged} 首暂无主题</span><span>故事来自歌词标签</span>`;}
 }
 function sourceLabel(source){
  if(source.kind==='single')return '单曲加入';
  if(source.criteria?.manual)return '全库手选';
  const name={country:'地区',energy:'氛围',themes:'主题',star:'星图框选',search:'搜索',library:'全库',selection:'选择'}[source.kind]||'来源';
  return name+'：'+(source.kind==='star'?describeSource(source):source.label||source.description||'已保存');
 }
 function renderRows(){
  const tracks=visible(),chosen=selection(),focused=!!focusedId,source=sourceOfSelection();
  const saved=new Set((data.playlist.songs||[]).filter(s=>!s.missing).map(s=>s.content));
  const canAdd=chosen.length&&!busy;
  const label=focused?'加入我的预备歌单':manualIds.size?'加入所选歌曲':'整板块加入预备歌单';
  const title=musicView==='all'?'全库歌单':focused?'选中单曲':source?.label||'选中歌曲';
  root.querySelector('.results-top').innerHTML=`<h2 class="results-title">${esc(title)}<small>${tracks.length} 首</small></h2><p class="selection-detail">${esc(musicView==='all'?'勾选形成待加入选择；歌曲保存在我的预备歌单。':focused?'点击播放可试听，点击加入才会保存。':source?describeSource(source):'点击单曲、板块或从全库勾选歌曲。')}</p><div class="results-actions"><button data-do="play-results" ${!tracks.some(t=>t.playable!==false)?'disabled':''}>${icon('play')}播放</button><button class="mutation-control" data-do="add-results" ${!canAdd?'disabled':''}>${icon('plus')}${label}</button>${chosen.length?'<button data-do="clear-selection">清除选中</button>':''}</div>`;
  root.querySelector('.table-head').innerHTML=`<span>${musicView==='all'?'挑选':'#'}</span><span>歌曲 / 歌手</span><span class="album-heading">专辑</span><span>时长</span><span></span>`;
  const limit=musicView==='all'?libraryCount:selectionCount;
  root.querySelector('.song-list').innerHTML=tracks.length?tracks.slice(0,limit).map((t,i)=>`<div class="song-row ${playing===t.id?'playing':''} ${focusedId===t.id?'focused-song':''}" data-focus-song="${esc(t.id)}"><span class="single-check">${musicView==='all'?`<input class="song-check" type="checkbox" data-pick="${esc(t.id)}" ${manualIds.has(t.id)?'checked':''} aria-label="选择 ${esc(t.title)}">`:i+1}</span><div class="song-main"><button class="song-name" data-focus="${esc(t.id)}">${esc(t.title)}</button><p class="song-meta">${esc(t.artist)}</p>${saved.has(t.contentId)?'<span class="source-badge">已加入预备歌单</span>':''}</div><span class="album-name" title="${esc(t.album)}">${esc(t.album||'—')}</span><span class="duration">${time(t.duration)}</span><div class="row-actions"><button class="icon-button" data-play="${esc(t.id)}" ${t.playable===false?'disabled':''} aria-label="播放 ${esc(t.title)}">${icon('play')}</button>${t.playable===false&&t.qqUrl?`<a href="${esc(t.qqUrl)}" target="_blank" rel="noopener noreferrer">QQ ↗</a>`:''}</div></div>`).join(''):'<div class="empty">还没有选中歌曲。<br>点击单曲、板块，或从全库勾选。</div>';
  root.querySelector('.more').hidden=tracks.length<=limit;
  musicTabs.querySelector('[data-music-view="selected"]').textContent='选中歌曲'+(chosen.length?'（'+chosen.length+'）':'');
  musicTabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.musicView===musicView)));
 }
 function renderPlaylist(){
  const ids=byId(),songs=data.playlist.songs||[];
  root.querySelector('.playlist-name').textContent=data.playlist.name;
  root.querySelector('.playlist-count').textContent=`${songs.length} 首${data.playlist.missing?' · '+data.playlist.missing+' 首待找回':''} · 每首保留加入来源`;
  root.querySelector('.prep-badge').textContent=songs.length+' 首';
  const undoButton=root.querySelector('[data-do="undo-delete"]');clearTimeout(undoTimer);
  undoButton.textContent=data.undoLabel||'撤销删除';
  root.querySelector('[data-do="clear-playlist"]').disabled=busy||!songs.length;
  root.querySelector('[data-do="export-zip"]').disabled=busy||!songs.length;
  root.querySelector('[data-do="export"]').disabled=busy||!songs.length;
  root.querySelector('.export-guidance').textContent=data.demoMode?'推荐 M3U8：轻量保存歌单，播放需对应歌曲文件。音乐 ZIP 为可选项，包含 MP3，体积较大。':'M3U8 保存歌单清单，播放需对应歌曲文件；可选音乐 ZIP，携带 MP3 离线播放。';
  const zip=data.zipDownload,status=root.querySelector('.zip-export-status');
  status.hidden=!zip&&!data.zipMessage;
  status.innerHTML=(zip?`<a href="${esc(zip.url)}" download="${esc(zip.name)}">${icon('download')}下载音乐ZIP</a> · ${zip.count} 首 MP3 · ${(zip.size/1024/1024).toFixed(1)} MB<br>`:'')+esc(data.zipMessage||'');
  undoButton.hidden=!data.undoUntil;undoButton.disabled=busy||!data.undoUntil;
  if(data.undoUntil)undoTimer=setTimeout(()=>{undoButton.hidden=true;undoButton.disabled=true;},Math.max(0,data.undoUntil*1000-Date.now()));
  root.querySelector('.playlist-list').innerHTML=songs.map((song,i)=>{
   const t=ids.get(song.id),title=t?.title||song.title;
   const labels=[...new Set(song.sources.map(sourceLabel))];
   return `<article class="prep-single" data-content="${esc(song.content)}"><div class="song-main"><button class="song-name" data-focus="${esc(song.id||'')}" ${!song.id?'disabled':''}>${esc(title)}</button><p class="song-meta">${esc(t?.artist||'待找回')}</p><span class="source-badge">${esc(labels.join(' · '))}</span></div><button class="icon-button" data-play="${esc(song.id||'')}" ${!t||t.playable===false?'disabled':''} aria-label="播放 ${esc(title)}">${icon('play')}</button><div class="entry-actions"><button class="icon-button mutation-control" data-song-move="${esc(song.content)}" data-offset="-1" ${i===0||busy?'disabled':''} aria-label="向前移动 ${esc(title)}">${icon('up')}</button><button class="icon-button mutation-control" data-song-move="${esc(song.content)}" data-offset="1" ${i===songs.length-1||busy?'disabled':''} aria-label="向后移动 ${esc(title)}">${icon('down')}</button><button class="icon-button mutation-control" data-song-delete="${esc(song.content)}" ${busy?'disabled':''} aria-label="删除 ${esc(title)}">${icon('close')}</button></div></article>`;
  }).join('')||'<div class="empty">唱片盒还是空的。<br>在选中歌曲中明确加入后，来这里整理。</div>';
  const select=root.querySelector('.saved-playlists');select.hidden=!data.savedPlaylists.length;select.innerHTML='<option value="">打开已保存的预备歌单…</option>'+data.savedPlaylists.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${p.count} 首</option>`).join('');
 }
 function playNext(offset){const list=playbackFromPlaylist?data.playlist.ids.filter(id=>byId().get(id)?.playable!==false):visible().filter(t=>t.playable!==false).map(t=>t.id);if(!list.length)return;const i=list.indexOf(playing);emit({kind:'play',id:list[(i+offset+list.length)%list.length]});}
 function addVisible(anchor){
  const tracks=selection();if(!tracks.length)return;
  if(focusedId)emit({kind:'set_single',id:focusedId,selected:true},anchor);
  else emit({kind:'add_group',ids:tracks.map(t=>t.id),source:sourceOfSelection()},anchor);
 }
 root.addEventListener('change',e=>{
  const checkbox=e.target.closest('[data-pick]');if(!checkbox)return;
  if(!manualIds.size){clearCurrent();}
  if(checkbox.checked)manualIds.add(checkbox.dataset.pick);else manualIds.delete(checkbox.dataset.pick);
  selectionEpoch++;renderStage();renderRows();
 });
 root.addEventListener('click',e=>{
  if(e.target.closest('[data-pick],a'))return;
  if(e.target.closest('.prep-backdrop')){setDrawer(false);return;}
  const region=e.target.closest('[data-region-scene]');if(region){chooseScene(Number(region.dataset.regionScene),'energy');return;}
  const b=e.target.closest('button');
  if(!b){const row=e.target.closest('[data-focus-song]');if(row)focusSong(row.dataset.focusSong);return;}
  if(b.disabled)return;
  if(b.dataset.musicView){showMusic(b.dataset.musicView);return;}
  if(b.dataset.tab){tab=b.dataset.tab;renderStage();return;}
  if(b.dataset.focus){focusSong(b.dataset.focus);if(drawerOpen)setDrawer(false);return;}
  if(b.dataset.play){playbackFromPlaylist=!!b.closest('.prep-drawer');emit({kind:'play',id:b.dataset.play});return;}
  if(b.dataset.add){emit({kind:'set_single',id:b.dataset.add,selected:true},b.closest('.song-row'));return;}
  if(b.dataset.songDelete){emit({kind:'delete_song',content:b.dataset.songDelete});return;}
  if(b.dataset.songMove){emit({kind:'move_song',content:b.dataset.songMove,offset:Number(b.dataset.offset)});return;}
  if(b.dataset.viewEntry){const entry=(data.playlist.entries||[]).find(p=>p.id===b.dataset.viewEntry);if(entry){resetFocus();if(entry.kind==='group'){replayEntry=entry;showMusic('selected');}else if(entry.ids.length){filter=null;clearedSelection=true;focusSong(entry.ids[0]);}setDrawer(false);revealMusic();}return;}
  if(b.dataset.scene!==undefined){chooseScene(Number(b.dataset.scene),b.dataset.sceneKind);return;}
  if(b.dataset.query){replaceSelection(()=>{inputText=b.dataset.query;root.querySelector('[name=query]').value=inputText;emit({kind:'query',text:inputText},b);renderStage();renderRows();});return;}
  switch(b.dataset.do){
   case 'drawer-toggle':if(!suppressBallClick)setDrawer(!drawerOpen);break;
   case 'reset-ball':ballPosition=null;placeBall();storeBall();break;
   case 'cancel-replace':closeReplace(false);break;
   case 'confirm-replace':closeReplace(true);break;
   case 'undo-delete':emit({kind:'undo_delete'});break;
   case 'clear-playlist':emit({kind:'clear_playlist'});break;
   case 'drawer-close':setDrawer(false);break;
   case 'scene-play':{const t=(filter?.ids||[]).map(id=>byId().get(id)).find(t=>t?.playable!==false);if(t)emit({kind:'play',id:t.id});break;}
   case 'scene-add':addVisible(b.closest('.landscape-selection'));break;
   case 'scene-create':if(filter?.ids.length){focusedId=null;replayEntry=null;musicView='selected';showName('results');root.querySelector('.rename-input').value=filter.label;}break;
   case 'manage':emit({kind:'manage'});break;
   case 'clear-star':clearCurrent();renderStage();renderRows();break;
   case 'all':showMusic('all');break;
   case 'clear-selection':clearCurrent();renderStage();renderRows();break;
   case 'return-selection':focusedId=null;showMusic('selected');break;
   case 'star':tab='sound';renderStage();root.querySelector('.sound-chart').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});break;
   case 'share':emit({kind:'share'});break;
   case 'more':if(musicView==='all')libraryCount+=12;else selectionCount+=12;renderRows();break;
   case 'unknown-region':setFilter('来源待补充',data.tracks.filter(t=>!t.country));break;
   case 'star-zoom-in':root._starView?.zoom(1.4);break;
   case 'star-zoom-out':root._starView?.zoom(1/1.4);break;
   case 'star-zoom-reset':root._starView?.reset();break;
   case 'star-pan-left':root._starView?.pan(60,0);break;
   case 'star-pan-right':root._starView?.pan(-60,0);break;
   case 'star-pan-up':root._starView?.pan(0,60);break;
   case 'star-pan-down':root._starView?.pan(0,-60);break;
   case 'zoom-in':zoom=Math.min(4,zoom+.15);root._globePaint?.();break;
   case 'zoom-out':zoom=Math.max(.7,zoom-.15);root._globePaint?.();break;
   case 'reset-globe':rotation=[-110,-20,0];zoom=1;root._globePaint?.();break;
   case 'play-results':{const t=visible().find(t=>t.playable!==false);if(t)emit({kind:'play',id:t.id});break;}
   case 'add-results':addVisible(b);break;
   case 'rename':showName('rename');break;
   case 'new':showName('empty');break;
   case 'new-results':if(selection().length)showName('results');break;
   case 'cancel-name':root.querySelector('.name-editor').hidden=true;break;
   case 'export':emit({kind:'export'});break;
   case 'export-zip':emit({kind:'export_zip'});break;
   case 'play-playlist':{const t=data.playlist.ids.find(id=>byId().get(id)?.playable!==false);if(t){playbackFromPlaylist=true;emit({kind:'play',id:t});}break;}
   case 'previous':playNext(-1);break;
   case 'next':playNext(1);break;
  }
 });
 root.addEventListener('keydown',e=>{
  if(pendingReplace){if(e.key==='Escape'){e.preventDefault();closeReplace(false);}else if(e.key==='Tab'){e.preventDefault();const buttons=[...root.querySelectorAll('.cover-dialog button')];buttons.find(b=>b!==root.getRootNode().activeElement)?.focus();}return;}
  if(!drawerOpen)return;
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();setDrawer(false);return;}
  if(e.key==='Tab'){const targets=[...root.querySelector('.prep-drawer').querySelectorAll('button:not(:disabled),input,select')].filter(el=>el.getClientRects().length);const active=root.getRootNode().activeElement;if(!targets.length)return;if(e.shiftKey&&active===targets[0]){e.preventDefault();targets.at(-1).focus();}else if(!e.shiftKey&&active===targets.at(-1)){e.preventDefault();targets[0].focus();}}
 });
 root.querySelector('.query-form').onsubmit=e=>{e.preventDefault();inputText=root.querySelector('[name=query]').value.trim();if(inputText){replaceSelection(()=>{emit({kind:'query',text:inputText},root.querySelector('.query-form'));renderStage();renderRows();});}};
 root.querySelector('[name=query]').oninput=e=>inputText=e.target.value;
 root.querySelector('.name-form').onsubmit=e=>{e.preventDefault();const name=root.querySelector('.rename-input').value.trim();if(!name)return;emit(naming==='rename'?{kind:'rename',name}:{kind:'create',name,ids:naming==='results'?selection().map(t=>t.id):[],source:sourceOfSelection()},naming==='results'?root.querySelector('.results-top'):null);root.querySelector('.name-editor').hidden=true;};
 root.querySelector('.saved-playlists').onchange=e=>{if(e.target.value)emit({kind:'switch',id:e.target.value});};
 audio.onended=()=>playNext(1);
 root._workspace={update(next){
  const active=root.getRootNode().activeElement;const focusKeys=['pick','play','focus','songDelete','songMove'];const focusKey=active?.dataset?focusKeys.find(k=>active.dataset[k]):null;const focusValue=focusKey?active.dataset[focusKey]:null;
  const previous=data;data=next.data;send=next.setTriggerValue;busy=false;root.classList.remove('busy');
  if(previous.analysis!==data.analysis){starTransform=d3.zoomIdentity;clearCurrent();musicView='all';libraryCount=12;playing=null;audio.pause();audio.removeAttribute('src');}
  const ack=data.actionResult,pending=pendingAction;
  const matched=pending&&ack?.token===pending.token;
  if(matched&&ack.success&&pending.kind==='query'&&pending.epoch===selectionEpoch&&data.results){resetFocus();filter=null;starBounds=null;manualIds.clear();clearedSelection=false;musicView='selected';}
  if(matched&&ack.success&&['set_single','add_group','create'].includes(pending.kind)&&pending.epoch===selectionEpoch){clearCurrent();musicView='selected';}
  else if(matched&&ack.success&&pending.kind==='add_group'&&pending.manual&&manualIds.size){pending.ids.forEach(id=>manualIds.delete(id));selectionEpoch++;}
  if(matched&&ack.success&&pending.kind==='query'&&ack.selectionSaved&&pending.epoch===selectionEpoch){clearCurrent();musicView='selected';}
  if(matched)pendingAction=null;
  if(data.download){const a=document.createElement('a');a.href=data.download.url;a.download=data.download.name;a.click();}
  if(matched&&ack.success&&pending.kind==='export_zip'&&data.zipDownload?.token===pending.token){const a=document.createElement('a');a.href=data.zipDownload.url;a.download=data.zipDownload.name;root.append(a);a.click();a.remove();}
  if(replayEntry){const saved=(data.playlist.entries||[]).find(e=>e.id===replayEntry.id);if(saved)replayEntry=saved;else{resetFocus();filter=null;clearedSelection=true;}}
  render();
  if(focusKey&&!active.isConnected){const attribute='data-'+focusKey.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());const restored=[...root.querySelectorAll('['+attribute+']')].find(el=>el.getAttribute(attribute)===focusValue&&!el.disabled);if(restored)restored.focus({preventScroll:true});else if(drawerOpen)root.querySelector('button[data-do=drawer-close]').focus();}
  if(pendingFlight&&data.actionResult?.token===pendingFlight.token){const flight=pendingFlight;pendingFlight=null;if(data.actionResult.success&&data.actionResult.added)animateAdded(flight);}
 }};
 function render(){
  root.querySelector('[data-do=manage]').innerHTML=icon('settings')+'管理曲境';
  root.querySelector('.notice').textContent=data.demoMode?(data.personalMode?'我的收藏 · 歌单仅保存在本次访问，可导出留存':'测试曲库 · 可在管理曲境连接 QQ 音乐 · 歌单可导出'):'画像依据收藏曲库 · 星座是声音分布的趣味表达 · 歌单保存在本机';
  root.querySelector('.library-count').textContent=`${data.tracks.length} 首收藏`;
  root.querySelector('.ai-status').textContent=data.aiReady?'AI 已配置 · 在你的收藏里找歌':(data.demoMode?'基础检索 · 演示曲库':'基础检索 · 在管理曲境中连接 AI');
  const previousMusicView=musicView;renderStage();renderRows();renderPlaylist();showMusic(previousMusicView);
  root.querySelector('.message').textContent=data.message||'';
  if(data.audio){const t=byId().get(data.audio.id);if(t){root.querySelector('.now-title').textContent=t.title;root.querySelector('.now-artist').textContent=t.artist;audio.hidden=false;root.querySelector('.player-empty').hidden=true;if(playing!==t.id||audio.getAttribute('src')!==data.audio.url){playing=t.id;audio.src=data.audio.url;audio.play().catch(()=>{root.querySelector('.message').textContent='歌曲已就绪，点击底部播放器开始试听。';});renderRows();}}}
 }
 render();
}
