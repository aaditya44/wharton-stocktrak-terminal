#!/bin/bash
N="${1:-8}"; count=0
while read -r sym sector; do
  [ -z "$sym" ] && continue
  f=$(python3 -c "print('data/bars_'+'$sym'.replace('^','I_').replace('=','_')+'_1y.json')")
  [ -f "$f" ] && continue
  [ "$count" -ge "$N" ] && break
  enc=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$sym', safe=''))")
  out=$(tools cloud_browser execute-js --lease-id "$LEASE" --tab-id "$TAB" --json --script "
try{
  const r = await fetch('https://query1.finance.yahoo.com/v8/finance/chart/$enc?range=1y&interval=1d');
  const j = await r.json();
  const res = j.chart.result[0];
  const ts=res.timestamp, q=res.indicators.quote[0];
  const rows=[];
  for(let i=0;i<ts.length;i++){ if(q.open[i]&&q.close[i]) rows.push([ts[i],q.open[i],q.close[i]]); }
  return JSON.stringify(rows);
}catch(e){ return 'ERR:'+String(e); }" </dev/null 2>/dev/null | python3 -c "import json,sys
try:
  d=json.load(sys.stdin)
  print(d.get('structured') or d.get('content','ERR:empty'))
except Exception: print('ERR:parse')")
  case "$out" in
    ERR*|'') echo "$sym: failed (${out:0:50})";;
    \[\[*) echo "$out" | python3 -c "import json,sys; json.dump(json.load(sys.stdin), open('$f','w'))" && echo "$sym: cached ($(echo "$out" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') bars)" && count=$((count+1));;
    *) echo "$sym: unexpected";;
  esac
  sleep 2
done < universe.txt
echo "cached this run: $count; total: $(ls data | grep -c '^bars_')/65"
