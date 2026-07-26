#!/usr/bin/env python3
import argparse,csv,html,json,re,time,urllib.request
from pathlib import Path
BASE='https://ggsel.net'; DEFAULT='https://ggsel.net/catalog/cgpt-plus-upgrade'; UA='Mozilla/5.0 Chrome/119 Safari/537.36'
def fetch(u): return urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'ru,en;q=0.9'}),timeout=30).read().decode('utf-8','replace')
def clean(s):
 s=re.sub(r'<script[^>]*>.*?</script>',' ',s,flags=re.S|re.I); s=re.sub(r'<style[^>]*>.*?</style>',' ',s,flags=re.S|re.I); s=re.sub(r'<[^>]+>','\n',s); s=html.unescape(s).replace('\xa0',' '); return '\n'.join(x.strip() for x in s.splitlines() if x.strip())
def objs(doc):
 seen={}
 for m in re.finditer(r'\{"id_goods":\d+.*?"in_favorites":(?:true|false)\}',doc):
  try: o=json.loads(m.group(0))
  except Exception: continue
  if o.get('url') and o.get('price_wmr_for_one') and (o.get('id_section')==98983 or 'GPT' in o.get('name','') or 'Чат' in o.get('name','')):
   seen[int(o['id_goods'])]=o
 return list(seen.values())
_SALES_RE = re.compile(r'product-stats-sell-count[^>]*>(\d+)', re.I)
_REVIEWS_RE = re.compile(r'product-stats-button[^>]*>(\d+)', re.I)
_RATING_RE = re.compile(r'data-testid="[^"]*rating[^"]*"[^>]*>\s*(\d+(?:\.\d+)?)', re.I)
_VARIANTS_RE = re.compile(r'"variants":\s*\[(\s*\{[^}{]*"(?:default|modify)[^}]*\}(?:\s*,\s*\{[^}{]*"(?:default|modify)[^}]*\})*)\s*\]', re.I)
_VARIANT_OBJ_RE = re.compile(r'\{\s*"value":\s*\d+,\s*"text":\s*"([^"]+)"[^}]*"modify":\s*"([^"]+)"[^}]*"default":\s*(true|false)', re.I)
_DAYS_RE = re.compile(r'\b(\d{1,3})\s*(?:дн(?:ей|я)?|д)\b', re.I)
_MONTHS_RE = re.compile(r'\b(\d{1,2})\s*(?:мес(?:яцев|яц)?|мес|month)s?\b', re.I)
_DELIV_PATTERNS = [
    ('shared-account', re.compile(r'\bобщ(ая|ий|ее|ee|ie|iy)?\b.{0,15}\b(доступ|аккаунт|подписк)|общ.{0,10}1\s*месяц|подписка\s*chatgpt\s*плюс\s*общ', re.I)),
    ('ready-account', re.compile(r'готов\w*\s*аккаунт|персональн\w+\s*аккаунт|personal\s*account|с\s*почт\w*|полный\s*доступ\s*к\s*почте|аккаунт\s*\+\s*почта', re.I)),
    ('own-login',     re.compile(r'на\s*ваш\w*\s*аккаунт|со\s*входом|на\s*вашем\s*аккаунте|на\s*вашу\s*почт\w*|продлен\w*|продлевается', re.I)),
    ('own-no-login',  re.compile(r'без\s*входа|без\s*логина|по\s*токену|активация\s*по\s*токену', re.I)),
]  # noqa: E501

def _classify_delivery(text):
    for delivery, pat in _DELIV_PATTERNS:
        if pat.search(text or ''):
            return delivery
    return 'unknown'

def _parse_variants(html_text):
    """Parse option variants from React state. Returns list of dicts {text, modify, default}.

    GGSEL page contains multiple '"variants":[…]' blocks (own card + recommendations).
    We pick the FIRST one — that's the product's own variants.
    """
    needle = '"variants":'
    idx = html_text.find(needle)
    if idx < 0: return []
    start = html_text.find('[', idx)
    if start < 0: return []
    depth = 1
    pos = start + 1
    n = len(html_text)
    while pos < n and depth > 0:
        c = html_text[pos]
        if c == '[': depth += 1
        elif c == ']': depth -= 1
        pos += 1
    if depth != 0: return []
    blob = html_text[start+1:pos-1]
    out = []
    for v in _VARIANT_OBJ_RE.finditer(blob):
        out.append({'text': v.group(1), 'modify': v.group(2), 'default': v.group(3) == 'true'})
    # If _VARIANT_OBJ_RE didn't catch them due to "default" being absent in this page format,
    # try a relaxed regex without "default"
    if not out:
        relaxed = re.compile(r'\{\s*"value":\s*\d+,\s*"text":\s*"([^"]+)"[^}]*"modify":\s*"([^"]+)"')
        for v in relaxed.finditer(blob):
            out.append({'text': v.group(1), 'modify': v.group(2), 'default': False})
    return out

def _rating_from_review_chunks(html_text):
    """Rating is typically rendered as a single line near the avatar; fall back to scanning first 200kB."""
    m = _RATING_RE.search(html_text)
    if m:
        try:
            r = float(m.group(1))
            if 0.0 <= r <= 5.0: return r
        except: pass
    m = re.search(r'\b([0-5]\.\d)\s*</[a-z]+>\s*</div>\s*<[^>]+>\s*\d+\s*продаж', html_text)
    if m:
        try: return float(m.group(1))
        except: pass
    return None

def detail(o):
 url=BASE+'/catalog/product/'+o['url']; out={'source':'ggsel','id':o.get('id_goods'),'name':o.get('name'),'seller':o.get('seller_name'),'sales':o.get('cnt_sell'),'rating':None,'price_rub':float(o.get('price_wmr_for_one') or 0),'url':url,'description':'','reviews_count':None,'browser_sales':None,'delivery':'unknown','variants':[],'variants_count':0,'duration_days':None,'duration_label':None,'base_price_rub':None,'error':''}
 try:
  html_text=fetch(url); t=clean(html_text); lines=t.splitlines()
  desc=''
  if 'О товаре' in lines:
   i=lines.index('О товаре'); end=len(lines)
   for mark in ['Раскрыть','Все сделки на ggsel','Рекомендовано вам']:
    if mark in lines[i+1:]: end=min(end,i+1+lines[i+1:].index(mark))
   desc=' '.join(lines[i+1:end])[:1200]
   out['description']=desc
  text_for_search=((o.get('name') or '') + ' ' + desc).lower()
  out['delivery']=_classify_delivery(text_for_search)
  rest=html_text
  for m in _SALES_RE.finditer(rest):
    n=int(m.group(1));
    if 0<n<100000:
     out['browser_sales']=n
     break
  for m in _REVIEWS_RE.finditer(rest):
    n=int(m.group(1));
    if 0<n<1000:
     out['reviews_count']=n
     break
  out['rating']=_rating_from_review_chunks(rest)
  variants = _parse_variants(rest)
  out['variants'] = variants
  out['variants_count'] = len(variants)
  base = float(o.get('price_wmr_for_one') or 0)
  out['base_price_rub'] = base
  # Compute the most-likely-30-day variant price
  if variants:
    thirty = None
    for v in variants:
      vdays = (re.search(r'(\d{1,3})\s*(?:д|дн)', v['text'], re.I)
              or re.search(r'(\d{1,2})\s*(?:мес|month)', v['text'], re.I))
      if vdays:
        if 'мес' in v['text'].lower() or 'month' in v['text'].lower():
          thirty = v; break
        if 'д' in v['text'].lower():
          n = int(vdays.group(1))
          if n in (28, 30, 31):
            thirty = v; break
    if thirty:
      m = re.search(r'([+-]?\d+(?:\.\d+)?)', thirty['modify'])
      if m:
        delta = float(m.group(1))
        out['price_rub'] = round(base + delta, 2)
        out['duration_days'] = 30
        out['duration_label'] = thirty['text'][:60]
 except Exception as e: out['error']=repr(e)
 return out
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--catalog',default=DEFAULT); ap.add_argument('--max-pages',type=int,default=5); ap.add_argument('--detail-every',type=int,default=1,help='Visit detail page every N items (1=every, 0=skip, -1=only unknown)'); ap.add_argument('--out-json',default='/tmp/best_price_helpers/chatgptplus/ggsel_results.json'); ap.add_argument('--out-csv',default='/tmp/best_price_helpers/chatgptplus/ggsel_results.csv'); ap.add_argument('--exclude-delivery',default='',help='Comma-separated delivery types to exclude, e.g. shared-account,unknown'); a=ap.parse_args()
 exclude=set([x.strip() for x in a.exclude_delivery.split(',') if x.strip()])
 products={}; stats=[]
 for p in range(1,a.max_pages+1):
  u=a.catalog if p==1 else a.catalog+('&' if '?' in a.catalog else '?')+'page='+str(p)
  doc=fetch(u); arr=objs(doc); new=0
  for o in arr:
   if o['id_goods'] not in products: products[o['id_goods']]=o; new+=1
  stats.append({'url':u,'found':len(arr),'new':new})
  if p>1 and new==0: break
 rows=[]
 catalog_items=list(products.values())
 for i,o in enumerate(catalog_items):
   need = (a.detail_every==0 and False) or (a.detail_every==-1) or (a.detail_every>0 and (i%a.detail_every==0))
   if a.detail_every==-1:
     quick_text=(o.get('name') or '').lower()
     quick_type=_classify_delivery(quick_text)
     need = (quick_type in exclude) or (quick_type=='unknown')
   if not need:
     rows.append({'source':'ggsel','id':o.get('id_goods'),'name':o.get('name'),'seller':o.get('seller_name'),'sales':o.get('cnt_sell'),'rating':None,'price_rub':float(o.get('price_wmr_for_one') or 0),'url':BASE+'/catalog/product/'+o.get('url',''),'description':'','reviews_count':None,'browser_sales':None,'delivery':'unknown','variants':[],'variants_count':0,'duration_days':None,'duration_label':None,'base_price_rub':None,'error':'detail skipped'})
   else:
     d=detail(o); d['sales']=d.get('browser_sales') or d.get('sales'); rows.append(d)
 rows.sort(key=lambda r:(r['price_rub'], -(r.get('sales') or 0)))
 res={'catalog':a.catalog,'count':len(rows),'page_stats':stats,'items':rows,'crawled_at_epoch':time.time(),'detail_every':a.detail_every,'exclude_delivery':sorted(exclude)}
 Path(a.out_json).parent.mkdir(parents=True,exist_ok=True); Path(a.out_json).write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
 with open(a.out_csv,'w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['source','id','price_rub','base_price_rub','duration_days','duration_label','variants_count','name','seller','sales','rating','browser_sales','reviews_count','delivery','url','description','error'],extrasaction='ignore'); w.writeheader(); w.writerows(rows)
 print('items:',len(rows));
 for r in rows[:5]: print(f"{r['price_rub']:.0f} RUB | {r['seller']} | sales={r['sales']} | rating={r.get('rating')} | {r.get('delivery')} | {r['name']}")
 print('json:',a.out_json); print('csv:',a.out_csv)
if __name__=='__main__': main()
