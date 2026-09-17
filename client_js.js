var CRULES={high:{vol_band:40,single_name_cap:15,leveraged_cap:15,event_cap:10},
medium:{vol_band:25,single_name_cap:10,leveraged_cap:5,event_cap:5},
low:{vol_band:15,single_name_cap:7,leveraged_cap:0,event_cap:5}};
var CBOOK={{BOOK}};
function crecompute(){
var tol=document.getElementById('c-tol').value,hor=+document.getElementById('c-hor').value;
var prefs=[...document.querySelectorAll('.c-pref:checked')].map(x=>x.value);
var R=CRULES[tol],flags=[];
var secOf={};
document.querySelectorAll('#crank tbody tr').forEach(function(r){secOf[r.children[1].textContent]=r.dataset.sector;});
document.querySelectorAll('#cpos tbody tr').forEach(function(r){
var sh=+r.querySelector('.c-sh').value||0,px=+r.dataset.px,val=sh*px,w=val/CBOOK*100;
r.querySelector('.c-val').textContent='$'+Math.round(val).toLocaleString();
r.querySelector('.c-w').textContent=w.toFixed(1)+'%';
r.dataset.w=w;});
document.querySelectorAll('#cpos tbody tr').forEach(function(r){
var sym=r.dataset.sym,w=+r.dataset.w,sec=secOf[sym]||'';
if(w>R.single_name_cap)flags.push(sym+' is ~'+w.toFixed(1)+'% of book - above the '+R.single_name_cap+'% single-name cap for a '+tol+'-tolerance profile');
if(sec==='LeveragedETF'&&w>R.leveraged_cap)flags.push(sym+' is a 3x leveraged ETF at ~'+w.toFixed(1)+'% of book - above the '+R.leveraged_cap+'% leveraged sleeve cap');
if(sec==='EventDriven'&&w>R.event_cap)flags.push(sym+' event-driven position ~'+w.toFixed(1)+'% exceeds the '+R.event_cap+'% event cap; gap risk is binary');});
if(hor<=3)flags.push('Horizon is short: error tolerance is compressed - prefer liquid names and pre-defined exits over positions that need time to work');
flags.push('Indicative analysis for a simulated competition account, not personalized financial advice; suitability follows the stated profile, never age alone');
document.getElementById('cflags').innerHTML=flags.map(function(f){return '<p class="flag">- '+f+'</p>';}).join('');
var rows=[...document.querySelectorAll('#crank tbody tr')];
rows.forEach(function(r){
var vol=+r.dataset.vol,sec=r.dataset.sector,base=+r.dataset.score;
var m=vol<=R.vol_band?1.0:(vol<=R.vol_band*1.5?0.6:0.2);
var note=vol<=R.vol_band?'inside vol band':(vol<=R.vol_band*1.5?'above band (capped)':'well outside band');
if(prefs.includes(sec)){m=Math.min(1,m+0.10);note+='; preferred sector';}
var cs=base*m+(prefs.includes(sec)?0.05:0);
r.dataset.cs=cs;
r.querySelector('.cm').textContent='x'+m.toFixed(2);
r.querySelector('.cs').innerHTML='<b>'+(cs>=0?'+':'')+cs.toFixed(3)+'</b>';
r.querySelector('.cn').textContent=note;});
rows.sort(function(a,b){return b.dataset.cs-a.dataset.cs;});
var tb=document.querySelector('#crank tbody');
rows.forEach(function(r,i){r.querySelector('.cr').textContent=i+1;tb.appendChild(r);});}
