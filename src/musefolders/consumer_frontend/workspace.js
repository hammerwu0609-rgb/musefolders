// D3 and Natural Earth geometry are bundled locally by consumer_ui.py.
const icons = {
 music:'M9 18V5l12-2v13M9 8l12-2M9 18a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Zm12-2a3 3 0 1 1-3-3c1.7 0 3 1.3 3 3Z',
 play:'m9 5 11 7-11 7Z', plus:'M12 5v14M5 12h14', check:'m5 12 4 4L19 6', close:'m6 6 12 12M6 18 18 6',
 settings:'M4 7h16M4 17h16M8 4v6M16 14v6', share:'M12 16V3m-5 5 5-5 5 5M5 13v7h14v-7',
 arrow:'M5 12h14m-6-6 6 6-6 6', down:'M5 12h14m-6-6 6 6-6 6', reset:'M3 10a9 9 0 1 1 2 8M3 4v6h6',
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
 let showConstellation=false;
 const byId = () => new Map(data.tracks.map(t=>[t.id,t]));
 const emit = action => {
  if(busy) return;
  busy=true;root.classList.add('busy');
  root.querySelector('.message').textContent = action.kind==='query' ? '正在理解你的描述…' : '正在处理…';
  send('action',{...action,token:Date.now()});
 };
 root.innerHTML = `
 <header class="topbar"><div class="brand">${icon('music')}曲境<small>MUSEFOLDERS</small></div><div class="top-actions"><span class="library-count"></span><button data-do="all">我的收藏</button><button data-do="manage">${icon('settings')}管理曲库</button></div></header>
 <div class="section-heading"><div><h2>你的音乐世界</h2><p>从收藏里，听见不同的自己</p></div></div>
 <div class="explore"><section class="atlas" aria-label="探索音乐收藏"><nav class="tabs" role="tablist" aria-label="探索方式"><button role="tab" data-tab="map">音乐星球</button><button role="tab" data-tab="sound">听感空间</button><button role="tab" data-tab="themes">主题河流</button></nav><div class="stage" role="tabpanel"></div><div class="atlas-caption"></div></section></div>
 <section class="composer" aria-label="找歌与整理歌单"><div class="composer-head"><h2>想听什么？</h2><span class="ai-status"></span></div><form class="query-form">${icon('search')}<input name="query" aria-label="描述想听的歌曲或歌单操作" maxlength="500" placeholder="找一些睡前听的歌，或把搜索结果建成歌单" autocomplete="off"><button class="green-button" type="submit">找歌 ${icon('arrow')}</button></form><div class="suggestions"><button data-query="关于爱情的歌">关于爱情的歌</button><button data-query="睡前听的歌">睡前听的歌</button><button data-query="运动时听的歌">运动时听的歌</button><button data-do="new-results">把结果建成歌单</button></div><div class="message" aria-live="polite" role="status"></div></section>
 <div class="lower"><section class="results" aria-label="歌曲列表"><div class="results-top"><h2 class="results-title"></h2><div class="results-actions"><button data-do="play-results">${icon('play')}播放</button><button data-do="add-results">${icon('plus')}加入歌单</button><button data-do="all">全部收藏</button></div></div><div class="table-head"><span>#</span><span>歌曲 / 歌手</span><span class="album-heading">专辑</span><span>时长</span><span></span></div><div class="song-list"></div><button class="more" data-do="more">显示更多歌曲</button></section>
 <aside class="playlist"><div class="playlist-top"><button class="playlist-name" data-do="rename" title="修改歌单名称"></button><button class="icon-button" data-do="rename" aria-label="修改歌单名称">${icon('edit')}</button></div><div class="playlist-count"></div><div class="name-editor" hidden><form class="name-form"><input class="rename-input" maxlength="60" aria-label="歌单名称" placeholder="歌单名称"><div class="playlist-tools"><button class="green-button" type="submit">保存</button><button class="outline-button" type="button" data-do="cancel-name">取消</button></div></form></div><select class="saved-playlists" aria-label="打开本地歌单" hidden></select><div class="playlist-tools"><button class="outline-button" data-do="new">${icon('plus')}新建</button><button class="outline-button" data-do="export">${icon('download')}导出</button><button class="outline-button" data-do="play-playlist">${icon('play')}播放</button></div><div class="playlist-list"></div></aside></div>
 <p class="notice">画像依据收藏曲库 · 星座是声音分布的趣味表达 · 歌单保存在本机</p>
 <footer class="player" aria-label="音乐播放器"><div class="now-playing"><div class="record">${icon('music')}</div><div class="song-main"><div class="song-name now-title">选择一首收藏</div><p class="song-meta now-artist">点击歌曲旁的播放按钮试听</p></div></div><audio controls preload="metadata" hidden aria-label="当前歌曲播放控制"></audio><div class="player-empty">好歌一直都在，随时再听一遍</div><div class="play-switch"><button class="icon-button" data-do="previous" aria-label="上一首">${icon('previous')}</button><button class="icon-button" data-do="next" aria-label="下一首">${icon('next')}</button></div></footer>`;
 // Keep exploration and its songs together, with a persistent music sidebar.
 const layout=document.createElement('main');layout.className='workspace-layout';
 const exploration=root.querySelector('.explore');
 exploration.before(layout);layout.append(exploration);
 const sidebar=document.createElement('aside');sidebar.className='music-sidebar';sidebar.setAttribute('aria-label','找歌与歌单');
 layout.append(sidebar);sidebar.append(root.querySelector('.composer'));
 const musicTabs=document.createElement('nav');musicTabs.className='music-tabs';musicTabs.setAttribute('aria-label','音乐区');
 musicTabs.innerHTML='<button data-music-view="results" aria-pressed="true">当前歌曲</button><button data-music-view="playlist" aria-pressed="false">我的歌单</button>';
 sidebar.append(musicTabs,root.querySelector('.lower'));
 let musicView='results';
 function showMusic(view){musicView=view;root.querySelector('.results').hidden=view!=='results';root.querySelector('.playlist').hidden=view!=='playlist';musicTabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.musicView===view)));}
 function revealMusic(){if(matchMedia('(max-width: 760px)').matches)sidebar.scrollIntoView({block:'start',behavior:'smooth'});}
 showMusic('results');
 const audio=root.querySelector('audio');
 let naming='rename';
 function visible(){
  const ids=byId();
  if(filter) return filter.ids.map(id=>ids.get(id)).filter(Boolean);
  if(data.results) return data.results.hits.map(h=>ids.get(h.id)).filter(Boolean);
  return data.tracks;
 }
 function setFilter(label,tracks){showMusic('results');starBounds=null;filter={label,ids:tracks.map(t=>t.id)};count=12;renderRows();revealMusic();}
 function showName(mode){showMusic('playlist');naming=mode;root.querySelector('.name-editor').hidden=false;const input=root.querySelector('.rename-input');input.value=mode==='rename'?data.playlist.name:'';input.placeholder=mode==='rename'?'歌单名称':'给新歌单起个名字';input.focus();}
 function drawStar(svg,mini=false){
  const side=mini?260:560, margin=mini?{l:8,r:8,t:8,b:8}:{l:58,r:20,t:22,b:54};
  const plot=side-margin.l-margin.r,height=plot+margin.t+margin.b;
  const s=d3.select(svg).attr('viewBox',`0 0 ${side} ${height}`);s.selectAll('*').remove();
  const x=d3.scaleLinear().domain([0,100]).range([margin.l,margin.l+plot]);
  const y=d3.scaleLinear().domain([0,100]).range([margin.t+plot,margin.t]);
  for(const tick of [0,25,50,75,100]){
   s.append('line').attr('x1',x(tick)).attr('x2',x(tick)).attr('y1',margin.t).attr('y2',margin.t+plot).attr('stroke','#2e3c33').attr('stroke-width',.7);
   s.append('line').attr('y1',y(tick)).attr('y2',y(tick)).attr('x1',margin.l).attr('x2',margin.l+plot).attr('stroke','#2e3c33').attr('stroke-width',.7);
   if(!mini){s.append('text').attr('x',x(tick)).attr('y',margin.t+plot+22).attr('text-anchor','middle').attr('fill','#a4b6a9').attr('font-size',11).text(tick);s.append('text').attr('x',margin.l-12).attr('y',y(tick)+4).attr('text-anchor','end').attr('fill','#a4b6a9').attr('font-size',11).text(tick);}
  }
  if(!mini){s.append('text').attr('x',margin.l+plot/2).attr('y',height-5).attr('text-anchor','middle').attr('fill','#b3c5b8').attr('font-size',12).text('节奏指数 · 慢 → 快');s.append('text').attr('transform',`translate(16,${margin.t+plot/2}) rotate(-90)`).attr('text-anchor','middle').attr('fill','#b3c5b8').attr('font-size',12).text('明亮度 · 暗 → 亮');}
  for(const [a,b] of (showConstellation?data.star.edges:[])){const p=data.star.nodes[a],q=data.star.nodes[b];s.append('line').attr('x1',x(p[0])).attr('x2',x(q[0])).attr('y1',y(p[1])).attr('y2',y(q[1])).attr('stroke','#82ac8e').attr('stroke-width',mini?1.3:1.8).attr('opacity',.8);}
  for(const p of (showConstellation?data.star.nodes:[]))s.append('circle').attr('cx',x(p[0])).attr('cy',y(p[1])).attr('r',mini?2:3).attr('fill','#9dccaa');
  const color=d3.scaleLinear().domain([0,50,100]).range(['#87a9df','#b7c8bf','#e9a76d']);
  const dots=s.selectAll('.plot-dot').data(data.tracks.filter(t=>t.x!==null)).join('circle').attr('class','plot-dot').attr('cx',t=>x(t.x)).attr('cy',t=>y(t.y)).attr('r',mini?3:5.8).attr('fill',t=>color(t.activity??50)).attr('opacity',.86);
  dots.append('title').text(t=>`${t.title} · ${t.artist}`);
  if(!mini){
   const brush=d3.brush().extent([[margin.l,margin.t],[margin.l+plot,margin.t+plot]]).on('end',e=>{
    if(!e.sourceEvent)return;
    showMusic('results');
    starBounds=e.selection;
    if(starBounds){const [[x0,y0],[x1,y1]]=starBounds;const chosen=data.tracks.filter(t=>t.x!==null&&x(t.x)>=x0&&x(t.x)<=x1&&y(t.y)>=y0&&y(t.y)<=y1);filter={label:'星图选中的歌曲',ids:chosen.map(t=>t.id),kind:'star'};count=12;}
    else if(filter?.kind==='star')filter=null;
    paintSelection();landscape('energy',root.querySelector('.sound-map'));renderRows();
   });
   const layer=s.insert('g','.plot-dot').attr('class','star-brush').call(brush);
   layer.select('.overlay').attr('aria-label','拖动框选星图中的歌曲');
   function paintSelection(){const linked=filter?.kind==='star'||filter?.kind==='energy';const selected=new Set(linked?filter.ids:[]);dots.classed('selected',t=>selected.has(t.id)).attr('opacity',t=>linked&&!selected.has(t.id)?.24:.9);const status=root.querySelector('.star-selection');if(status)status.textContent=starBounds?`已选 ${selected.size} 首 · 下方可试听、加入或创建歌单`:filter?.kind==='energy'?`${filter.label} · 高亮 ${selected.size} 首`:'在图中空白处拖动框选，或点击歌曲圆点试听';const clear=root.querySelector('[data-do="clear-star"]');if(clear)clear.disabled=!linked;}
   if(starBounds)layer.call(brush.move,starBounds);
   paintSelection();
   svg.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();layer.call(brush.move,null);starBounds=null;if(filter?.kind==='star')filter=null;paintSelection();landscape('energy',root.querySelector('.sound-map'));renderRows();}};
  }
  if(!mini){dots.attr('tabindex' ,0).attr('role','button').attr('aria-label',t=>`播放 ${t.title}`).on('click',(e,t)=>emit({kind:'play',id:t.id})).on('keydown',(e,t)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();emit({kind:'play',id:t.id});}});}
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
  function chooseRegion(id,name,center){showMusic('results');rotation=[-center[0],-center[1],0];paint();filter={label:name,ids:data.tracks.filter(t=>t.country===id).map(t=>t.id),country:id};count=12;paint();renderRows();renderRegions();}
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
 function chooseScene(index,kind){showMusic('results');
  const group=(kind==='energy'?atmospheres:stories)[index];
  if(!group)return;
  starBounds=null;filter={label:group.name,ids:sceneSongs(group,kind).map(t=>t.id),kind,scene:index};count=12;
  renderStage();renderRows();
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
    return `<button class="song-light ${x<25?'tooltip-start':x>75?'tooltip-end':''} ${active&&active!==group?'dimmed':''} ${playing===song.id?'playing':''}" data-play="${esc(song.id)}" data-scene-light="${index}" style="--x:${x}%;--y:${y}%;--mobile-x:${mx}%;--mobile-y:${my}%" aria-label="播放 ${esc(song.title)} · ${esc(song.artist)}"><span class="light-ripple"></span><span class="light-core"></span><span class="light-tooltip"><strong>${esc(song.title)}</strong><small>${esc(song.artist)}</small><em>点击试听</em></span></button>`;
   }).join('');
  }).join('');
  const title=energy?'氛围地图':'主题河流',subtitle=energy?'收藏里的声音，长成一片风景':'顺着歌词，走过收藏里的故事';
  target.innerHTML=`<section class="landscape-panel ${energy?'sound-landscape':'story-landscape'}" aria-label="${title}"><div class="landscape-canvas"><div class="landscape-art" aria-hidden="true"></div><div class="landscape-shade" aria-hidden="true"></div><div class="landscape-heading"><h3>${title}</h3><p>${subtitle}</p></div>${regions}<div class="landscape-places">${labels}</div><div class="landscape-lights">${lights}</div><div class="landscape-hint">${energy?'点击一片风景，发现其中的歌曲':'点击河畔主题，听一段收藏里的故事'}</div></div><div class="landscape-selection" aria-live="polite"><div><span class="selection-eyebrow">${active?'你正在探索':'从收藏出发'}</span><h4>${active?esc(active.name):energy?'想去哪里听听？':'沿河，遇见一段故事'} ${active?`<small>${selected.length} 首</small>`:''}</h4><p>${active?esc(active.note):'点击地点查看歌曲，点击光点试听'}${active&&!selected.length?' · 收藏中暂时没有匹配歌曲':''}</p></div><div class="landscape-actions"><button class="green-button" data-do="scene-play" ${!selected.length?'disabled':''}>${icon('play')}试听</button><button class="outline-button" data-do="scene-add" ${!selected.length?'disabled':''}>加入歌单</button><button class="outline-button" data-do="scene-create" ${!selected.length?'disabled':''}>创建歌单</button></div></div></section>`;
 }
 function renderStage(){
  root.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tab===tab)));
  const stage=root.querySelector('.stage'),caption=root.querySelector('.atlas-caption');
  if(tab==='map'){drawGlobe();stage.insertAdjacentHTML('afterbegin','<p class="view-intro">按艺人关联地区，探索收藏里的世界</p>');caption.innerHTML='<span>滚轮缩放 · 拖动旋转 · 点击地区听歌</span><span>地区资料来自艺人档案</span>';}
  if(tab==='sound'){
   stage.innerHTML='<section class="sound-space" aria-label="听感空间"><p class="view-intro">同一份收藏，上面看声音分布，下面按氛围探索。</p><section class="sound-chart" aria-label="声音星图"><div class="sound-chart-heading"><div><h3>声音星图</h3><p>每颗星是一首收藏，位置来自声音特征，可拖动框选歌曲。</p></div><details class="sound-principle"><summary>图怎么看</summary><p>横向表示节奏指数，纵向表示明亮度，颜色表示活跃度。连线是根据整库声音分布匹配的趣味星座轮廓。</p></details></div><div class="star-tools"><span class="star-selection" role="status"></span><button class="outline-button" data-do="clear-star">清除筛选</button></div><svg class="full-star" tabindex="0" aria-label="节奏与明亮度的声音星图，可拖动框选歌曲，按 Escape 清除选区"></svg><p class="sound-legend">颜色：活跃度低 → 高 · 点击下方风景，高亮对应歌曲</p></section><details class="constellation-option"><summary>专属星座与分享 <span>可选 · 根据收藏自动生成</span></summary><div class="constellation-content"><h3 class="star-name"></h3><p class="profile-note"></p><button class="outline-button" data-do="share">分享我的星座</button><div class="share-preview"></div></div></details><div class="sound-map"></div></section>';
   const option=stage.querySelector('.constellation-option');option.open=showConstellation;
   option.ontoggle=()=>{showConstellation=option.open;drawStar(stage.querySelector('.full-star'));};
   stage.querySelector('.star-name').textContent=data.star.name;
   stage.querySelector('.profile-note').textContent=data.star.status==='matched'?`由 ${data.star.measured??data.tracks.length} 首已分析收藏的声音分布自动生成，展开时在图中显示星座轮廓。`:'需要 12 首有音频分析的不同录音，才能生成音乐星座。';
   stage.querySelector('[data-do=share]').disabled=data.star.status!=='matched';
   stage.querySelector('.share-preview').innerHTML=data.share?`<img src="${esc(data.share)}" alt="我的音乐星座分享卡"><a href="${esc(data.share)}" download="我的音乐星座.png">下载我的星座分享卡 ${icon('download')}</a>`:'';
   landscape('energy',stage.querySelector('.sound-map'));drawStar(stage.querySelector('.full-star'));
   caption.innerHTML='<span>将歌曲的活跃度与明亮度化成风景，点击地点听歌</span><span>地点包含全部匹配歌曲</span>';
  }
  if(tab==='themes'){landscape('themes');stage.insertAdjacentHTML('afterbegin','<p class="view-intro">从歌词中提取主题，沿着河流发现相似的故事</p>');const tagged=data.tracks.filter(t=>t.themes.length).length;caption.innerHTML=`<span>一首歌可以流经多个故事 · ${data.tracks.length-tagged} 首暂无主题</span><span>故事来自歌词标签</span>`;}
 }
 function renderRows(){
  const tracks=visible(),selected=new Set(data.playlist.ids),reasons=new Map((data.results?.hits||[]).map(h=>[h.id,h.reasons.join(' · ')]));
  root.querySelector('.results-title').innerHTML=`${esc(filter?.label||data.results?.query||'我的收藏')}<small>${tracks.length} 首</small>`;
  root.querySelector('.song-list').innerHTML=tracks.length?tracks.slice(0,count).map((t,i)=>`<div class="song-row ${playing===t.id?'playing':''}"><span class="index">${String(i+1).padStart(2,'0')}</span><div class="song-main"><button class="song-name" data-play="${esc(t.id)}">${esc(t.title)}</button><p class="song-meta" title="${esc(reasons.get(t.id)||t.artist)}">${esc(t.artist)}${reasons.get(t.id)?' · '+esc(reasons.get(t.id)):''}</p></div><span class="album-name" title="${esc(t.album)}">${esc(t.album||'—')}</span><span class="duration">${time(t.duration)}</span><div class="row-actions">${t.playable===false?(t.qqUrl?`<a href="${esc(t.qqUrl)}" target="_blank" rel="noopener noreferrer" title="在 QQ 音乐打开">QQ音乐 ↗</a>`:'<small>暂无音频</small>'):''}<button class="icon-button" data-play="${esc(t.id)}" ${t.playable===false?'disabled':''} aria-label="播放 ${esc(t.title)}">${icon('play')}</button><button class="icon-button" data-add="${esc(t.id)}" ${selected.has(t.id)?'disabled':''} aria-label="${selected.has(t.id)?'已加入':'加入歌单'} ${esc(t.title)}">${icon(selected.has(t.id)?'check':'plus')}</button></div></div>`).join(''):`<div class="empty">${filter?.country?'这个地区暂时没有已确认来源的收藏。可以先听听“待补充”里的歌曲。':'没有找到匹配的歌曲。试试减少条件，或换个歌名、歌手。'}</div>`;
  root.querySelector('.more').hidden=tracks.length<=count;
 }
 function renderPlaylist(){
  const ids=byId(),tracks=data.playlist.ids.map(id=>ids.get(id)).filter(Boolean);
  root.querySelector('.playlist-name').textContent=data.playlist.name;
  root.querySelector('.playlist-count').textContent=`${tracks.length} 首 · 本地歌单${data.playlist.missing?' · '+data.playlist.missing+' 首文件待找回':''}`;
  root.querySelector('.playlist-list').innerHTML=tracks.length?tracks.map(t=>`<div class="playlist-row"><div class="song-main"><button class="song-name" data-play="${esc(t.id)}">${esc(t.title)}</button><p class="song-meta">${esc(t.artist)}</p></div><div class="row-actions"><button class="icon-button" data-move="${esc(t.id)}" data-offset="-1" aria-label="向前移动 ${esc(t.title)}">${icon('up')}</button><button class="icon-button" data-move="${esc(t.id)}" data-offset="1" aria-label="向后移动 ${esc(t.title)}"><svg class="icon" viewBox="0 0 24 24"><path d="m6 10 6 6 6-6"/></svg></button><button class="icon-button" data-remove="${esc(t.id)}" aria-label="移出歌单 ${esc(t.title)}">${icon('close')}</button></div></div>`).join(''):'<div class="empty">把喜欢的歌加入这里。<br>也可以在输入框描述一个歌单。</div>';
  const select=root.querySelector('.saved-playlists');select.hidden=!data.savedPlaylists.length;select.innerHTML='<option value="">打开已保存的歌单…</option>'+data.savedPlaylists.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${p.count} 首</option>`).join('');
 }
 function playNext(offset){const list=data.playlist.ids.includes(playing)?data.playlist.ids.filter(id=>byId().get(id)?.playable!==false):visible().filter(t=>t.playable!==false).map(t=>t.id);if(!list.length)return;const i=list.indexOf(playing);emit({kind:'play',id:list[(i+offset+list.length)%list.length]});}
 root.addEventListener('click',e=>{
  const region=e.target.closest('[data-region-scene]');if(region){chooseScene(Number(region.dataset.regionScene),'energy');return;}
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.musicView){showMusic(b.dataset.musicView);return;}
  if(b.dataset.tab){tab=b.dataset.tab;renderStage();return;}
  if(b.dataset.play){emit({kind:'play',id:b.dataset.play});return;}
  if(b.dataset.add){emit({kind:'add',id:b.dataset.add});return;}
  if(b.dataset.remove){emit({kind:'remove',id:b.dataset.remove});return;}
  if(b.dataset.move){emit({kind:'move',id:b.dataset.move,offset:Number(b.dataset.offset)});return;}
  if(b.dataset.scene!==undefined){chooseScene(Number(b.dataset.scene),b.dataset.sceneKind);return;}
  if(b.dataset.query){starBounds=null;inputText=b.dataset.query;root.querySelector('[name=query]').value=inputText;filter=null;emit({kind:'query',text:inputText});return;}
  switch(b.dataset.do){
   case 'scene-play':if(filter?.ids.length)emit({kind:'play',id:filter.ids[0]});break;
   case 'scene-add':if(filter?.ids.length)emit({kind:'add_many',ids:filter.ids});break;
   case 'scene-create':if(filter?.ids.length){showName('results');root.querySelector('.rename-input').value=filter.label;revealMusic();}break;
   case 'manage':emit({kind:'manage'});break;
   case 'clear-star':starBounds=null;if(filter?.kind==='star'||filter?.kind==='energy')filter=null;renderStage();renderRows();break;
   case 'all':showMusic('results');starBounds=null;filter=null;count=12;emit({kind:'all'});break;
   case 'star':tab='sound';renderStage();root.querySelector('.sound-chart').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});break;
   case 'share':emit({kind:'share'});break;
   case 'more':count+=12;renderRows();break;
   case 'unknown-region':setFilter('来源待补充',data.tracks.filter(t=>!t.country));break;
   case 'zoom-in':zoom=Math.min(4,zoom+.15);root._globePaint?.();break;
   case 'zoom-out':zoom=Math.max(.7,zoom-.15);root._globePaint?.();break;
   case 'reset-globe':rotation=[-110,-20,0];zoom=1;root._globePaint?.();break;
   case 'play-results':if(visible().length)emit({kind:'play',id:visible()[0].id});break;
   case 'add-results':if(visible().length)emit({kind:'add_many',ids:visible().map(t=>t.id)});break;
   case 'rename':showName('rename');break;
   case 'new':showName('empty');break;
   case 'new-results':showName('results');revealMusic();break;
   case 'cancel-name':root.querySelector('.name-editor').hidden=true;break;
   case 'export':emit({kind:'export'});break;
   case 'play-playlist':if(data.playlist.ids.length)emit({kind:'play',id:data.playlist.ids[0]});break;
   case 'previous':playNext(-1);break;
   case 'next':playNext(1);break;
  }
 });
 root.querySelector('.query-form').onsubmit=e=>{e.preventDefault();inputText=root.querySelector('[name=query]').value.trim();if(inputText){starBounds=null;filter=null;emit({kind:'query',text:inputText});}};
 root.querySelector('[name=query]').oninput=e=>inputText=e.target.value;
 root.querySelector('.name-form').onsubmit=e=>{e.preventDefault();const name=root.querySelector('.rename-input').value.trim();if(!name)return;emit(naming==='rename'?{kind:'rename',name}:{kind:'create',name,ids:naming==='results'?visible().map(t=>t.id):[]});root.querySelector('.name-editor').hidden=true;};
 root.querySelector('.saved-playlists').onchange=e=>{if(e.target.value)emit({kind:'switch',id:e.target.value});};
 audio.onended=()=>playNext(1);
 root._workspace={update(next){
  const previous=data;data=next.data;send=next.setTriggerValue;busy=false;root.classList.remove('busy');
  if(previous.analysis!==data.analysis){starBounds=null;filter=null;playing=null;audio.pause();audio.removeAttribute('src');}
  if(previous.results!==data.results&&JSON.stringify(previous.results)!==JSON.stringify(data.results)){starBounds=null;filter=null;count=12;musicView='results';}
  if(data.download){const a=document.createElement('a');a.href=data.download.url;a.download=data.download.name;a.click();}
  render();
 }};
 function render(){
  root.querySelector('[data-do=manage]').innerHTML=icon('settings')+'管理曲库';
  root.querySelector('.notice').textContent=data.demoMode?(data.personalMode?'我的收藏 · 歌单仅保存在本次访问，可导出留存':'测试曲库 · 可在管理曲库连接 QQ 音乐 · 歌单可导出'):'画像依据收藏曲库 · 星座是声音分布的趣味表达 · 歌单保存在本机';
  root.querySelector('.library-count').textContent=`${data.tracks.length} 首收藏`;
  root.querySelector('.ai-status').textContent=data.aiReady?'AI 已配置 · 在你的收藏里找歌':(data.demoMode?'基础检索 · 演示曲库':'基础检索 · 在管理曲库中连接 AI');
  const previousMusicView=musicView;renderStage();renderRows();renderPlaylist();showMusic(previousMusicView);
  root.querySelector('.message').textContent=data.message||'';
  if(data.audio){const t=byId().get(data.audio.id);if(t){root.querySelector('.now-title').textContent=t.title;root.querySelector('.now-artist').textContent=t.artist;audio.hidden=false;root.querySelector('.player-empty').hidden=true;if(playing!==t.id||audio.getAttribute('src')!==data.audio.url){playing=t.id;audio.src=data.audio.url;audio.play().catch(()=>{root.querySelector('.message').textContent='歌曲已就绪，点击底部播放器开始试听。';});renderRows();}}}
 }
 render();
}
