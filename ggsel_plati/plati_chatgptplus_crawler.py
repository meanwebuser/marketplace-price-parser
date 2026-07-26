#!/usr/bin/env python3
import argparse,csv,html,json,re,time,urllib.request
from pathlib import Path
BASE='https://plati.market'; DEFAULT='https://plati.market/games/chatgpt/1267/?id_c=7396'; UA='Mozilla/5.0 Chrome/119 Safari/537.36'
def fetch(u): return urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'ru,en;q=0.9'}),timeout=30).read().decode('utf-8','replace')
def txt(s): s=re.sub(r'<[^>]+>','\n',s); return '\n'.join(x.strip() for x in html.unescape(s).replace('\xa0',' ').splitlines() if x.strip())
def money(s):
 m=re.search(r'\d[\d\s]*(?:[.,]\d+)?',html.unescape(s).replace('\xa0',' ')); return float(m.group(0).replace(' ','').replace(',','.')) if m else 0.0
def norm(s): return (s or '').lower().replace('ё','е')
def matches_plan(text,plan):
 t=norm(text); p=norm(plan)
 if p in ('plus','плюс'): return ('plus' in t or 'плюс' in t) and not re.search(r'\bpro\b|\bgo\b|про\b', t)
 if p=='go': return re.search(r'\bgo\b|\bго\b', t) is not None
 if p in ('pro','про'): return re.search(r'\bpro\b|\bпро\b', t) is not None
 return p in t
def catalog_cards(doc):
 rows=[]; seen=set()
 for m in re.finditer(r'<a class="card[\s\S]*?</a>\s*</li>',doc,re.I):
  b=m.group(0); hm=re.search(r'href="([^"]+)"',b); im=re.search(r'product_id="(\d+)"',b); tm=re.search(r'title="([^"]+)"',b); pm=re.search(r'<span class="title-bold[^"]*">([\s\S]*?)</span>',b); sm=re.search(r"text-truncate'>(.*?)</span>",b,re.S) or re.search(r'text-truncate">(.*?)</span>',b,re.S); sold=re.search(r'Продано\s*([^<\n]+)',txt(b))
  if not (hm and pm): continue
  url=hm.group(1); url=BASE+url if url.startswith('/') else url; pid=im.group(1) if im else url
  if pid in seen: continue
  seen.add(pid)
  rows.append({'source':'plati','id':pid,'name':html.unescape(tm.group(1)).strip() if tm else '', 'seller':txt(sm.group(1)) if sm else None, 'sales':sold.group(1).strip() if sold else None, 'rating':None, 'price_rub':money(pm.group(1)), 'url':url, 'description':'', 'error':'', 'plan_price_source':'catalog_min'})
 return rows
def parse_detail_options(doc, base_price, plan):
 opts=[]
 # Each radio input contains data-delta-price; following label contains option text.
 pat=re.compile(r'<input[^>]+data-delta-price="([^"]*)"[\s\S]*?<label[^>]*>([\s\S]*?)</label>',re.I)
 for m in pat.finditer(doc):
  delta=money(m.group(1)); label=txt(m.group(2)); opts.append({'label':label,'delta':delta,'price_rub':round(base_price+delta,2)})
 matching=[o for o in opts if matches_plan(o['label'],plan)]
 if matching:
  return min(matching,key=lambda o:o['price_rub']), opts
 # If there are no options, accept whole product if title/body clearly matches plan.
 title=''; mt=re.search(r'<title>(.*?)</title>',doc,re.S|re.I)
 if mt: title=html.unescape(mt.group(1))
 if not opts and matches_plan(title,plan): return {'label':title,'delta':0,'price_rub':base_price}, opts
 return None, opts
def enrich(row, plan):
 try:
  doc=fetch(row['url'])
  best, opts=parse_detail_options(doc,row['price_rub'],plan)
  row['options'] = opts[:20]
  if best:
   row['price_rub'] = best['price_rub']; row['matched_plan_label']=best['label']; row['plan_price_source']='detail_option' if best.get('delta') else 'detail_title'
  else:
   row['error']='no matching plan option: '+plan; row['matched_plan_label']=''
 except Exception as e: row['error']=repr(e)
 return row
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--catalog',default=DEFAULT); ap.add_argument('--plan',default='plus'); ap.add_argument('--detail-limit',type=int,default=60); ap.add_argument('--out-json',default='/tmp/best_price_helpers/chatgptplus/plati_results.json'); ap.add_argument('--out-csv',default='/tmp/best_price_helpers/chatgptplus/plati_results.csv'); a=ap.parse_args()
 rows=catalog_cards(fetch(a.catalog))
 # Enrich only first N visible cards; enough for top sorting and fast enough.
 enriched=[]
 for r in rows[:a.detail_limit]:
  enriched.append(enrich(r,a.plan))
 for r in rows[a.detail_limit:]:
  r['error']='not enriched: over detail limit'; enriched.append(r)
 rows=[r for r in enriched if not r.get('error')]
 rows.sort(key=lambda r:(r['price_rub'], str(r.get('sales'))))
 res={'catalog':a.catalog,'plan':a.plan,'count':len(rows),'items':rows,'crawled_at_epoch':time.time(),'note':'price_rub is plan-specific when detail option matched; catalog min price may be GO.'}
 Path(a.out_json).parent.mkdir(parents=True,exist_ok=True); Path(a.out_json).write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
 fields=['source','id','price_rub','name','seller','sales','rating','url','matched_plan_label','plan_price_source','description','error']
 with open(a.out_csv,'w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
 print('items:',len(rows),'plan:',a.plan)
 for r in rows[:5]: print(f"{r['price_rub']:.0f} RUB | {r['seller']} | sales={r['sales']} | {r['name']} | plan={r.get('matched_plan_label','')[:80]}")
 print('json:',a.out_json); print('csv:',a.out_csv)
if __name__=='__main__': main()
