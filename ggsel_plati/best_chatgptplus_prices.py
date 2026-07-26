#!/usr/bin/env python3
import argparse,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=Path('/tmp/best_price_helpers/chatgptplus')
def run(c):
 p=subprocess.run(c,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode: raise RuntimeError(f"failed: {' '.join(map(str,c))}\n{p.stdout}\n{p.stderr}")
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
_DELIV_RISK={
 'own-login':'продавец зайдёт в твой аккаунт и активирует Plus',
 'own-no-login':'активация по токену/ссылке, пароль не нужен',
 'ready-account':'готовый чужой аккаунт, не на твоей почте',
 'shared-account':'общий аккаунт на нескольких покупателей (sleta risk)',
 'unknown':'тип выдачи не распознан автоматически',
}
_PURPOSE_PRESETS={
 # 'new-account': buying a pre-made account or having seller register on user's email
 # (no shared-use, no own-login/own-no-login)
 'new-account':  {'include': None, 'exclude': {'own-login','own-no-login','shared-account'}, 'shared_forbidden': True},
 # 'renew': продление на свой существующий аккаунт
 'renew':        {'include': {'own-login','own-no-login'}, 'exclude': {'shared-account'}, 'shared_forbidden': True},
 # 'any': что угодно
 'any':          {'include': None, 'exclude': set(), 'shared_forbidden': False},
}

def _match_purpose(o, preset):
    if preset['shared_forbidden'] and o.get('delivery') == 'shared-account':
        return False
    excl = preset.get('exclude') or set()
    if o.get('delivery') in excl:
        return False
    inc = preset.get('include')
    if inc is not None and o.get('delivery') not in inc:
        return False
    return True

def _sales_int(o):
    s = o.get('browser_sales') or o.get('sales')
    if isinstance(s, int): return s
    try: return int(str(s))
    except: return 0

def _fmt_row(i, o):
    sales = o.get('browser_sales') or o.get('sales')
    reviews = o.get('reviews_count')
    rating = o.get('rating')
    dur = o.get('duration_label') or (f"{o.get('duration_days')}д" if o.get('duration_days') else '?')
    p = o['price_rub']
    bits = []
    bits.append(f"{i}. {p:.0f} ₽ ({dur})")
    src = o.get('source','ggsel')
    bits.append(f"| {src} | {o.get('seller','-')}")
    bits.append(f"| sales={sales or '-'}")
    if reviews: bits.append(f"| reviews={reviews}")
    if rating is not None: bits.append(f"| rating={rating}")
    bits.append(f"| {o.get('delivery','?')}")
    title = (o.get('name') or '')[:90]
    return ' '.join(bits) + '\n   ' + title + '\n   ' + (o.get('url') or '')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--top',type=int,default=5)
    ap.add_argument('--plan',default='plus',help='Target plan, default: plus')
    ap.add_argument('--purpose',default='any',choices=list(_PURPOSE_PRESETS.keys()),help='High-level filter: new-account / renew / any')
    ap.add_argument('--exclude-delivery',default='',help='Comma-separated extra exclusions, e.g. unknown')
    ap.add_argument('--json',action='store_true')
    ap.add_argument('--ggsel-url',default='https://ggsel.net/catalog/cgpt-plus-upgrade')
    ap.add_argument('--plati-url',default='https://plati.market/games/chatgpt/1267/?id_c=7396')
    ap.add_argument('--max-pages',type=int,default=5)
    ap.add_argument('--detail-every',type=int,default=1)
    ap.add_argument('--detail-limit',type=int,default=30)
    ap.add_argument('--delivery',default='all',choices=['all','own-login','own-no-login','ready-account','shared-account','unknown'])
    ap.add_argument('--min-rating',type=float,default=0.0,help='Drop sellers below this rating (0..5)')
    ap.add_argument('--min-sales',type=int,default=0,help='Drop offers with fewer sales than this')
    ap.add_argument('--min-reviews',type=int,default=0)
    ap.add_argument('--plati-only',action='store_true',help='Skip Plati (faster).')
    ap.add_argument('--ggsel-only',action='store_true',help='Skip Plati completely.')
    ap.add_argument('--grouped',action='store_true')
    a=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    gj=OUT/'ggsel_results.json'; gc=OUT/'ggsel_results.csv'
    pj=OUT/'plati_results.json'; pc=OUT/'plati_results.csv'
    run([sys.executable,str(HERE/'ggsel_chatgptplus_crawler.py'),'--catalog',a.ggsel_url,'--max-pages',str(a.max_pages),'--detail-every',str(a.detail_every),'--out-json',str(gj),'--out-csv',str(gc)])
    if not a.ggsel_only:
        run(['node',str(HERE/'plati_chatgptplus_browser_crawler.js'),'--catalog',a.plati_url,'--plan',a.plan,'--detail-limit',str(a.detail_limit),'--out-json',str(pj),'--out-csv',str(pc)])
    offers=(load(gj).get('items',[])+load(pj).get('items',[]))
    offers=[o for o in offers if o.get('price_rub')]
    for o in offers:
        o.setdefault('delivery','unknown')
        o.setdefault('risk_note',_DELIV_RISK.get(o['delivery'],_DELIV_RISK['unknown']))
    purpose=_PURPOSE_PRESETS[a.purpose]
    extra_excl=set([x.strip() for x in a.exclude_delivery.split(',') if x.strip()])
    if extra_excl:
        purpose=dict(purpose); purpose['exclude']=(purpose.get('exclude') or set()) | extra_excl
    pre=len(offers); offers=[o for o in offers if _match_purpose(o, purpose)]
    if a.delivery!='all': offers=[o for o in offers if o.get('delivery')==a.delivery]
    if a.min_rating:
        offers=[o for o in offers if (o.get('rating') or 0) >= a.min_rating or o.get('rating') is None]
    if a.min_sales:
        offers=[o for o in offers if _sales_int(o) >= a.min_sales]
    if a.min_reviews:
        offers=[o for o in offers if (o.get('reviews_count') or 0) >= a.min_reviews]
    offers.sort(key=lambda o:(o['price_rub'], -_sales_int(o)))
    res={'top':a.top,'plan':a.plan,'purpose':a.purpose,'delivery':a.delivery,
         'filters':{'min_rating':a.min_rating,'min_sales':a.min_sales,'min_reviews':a.min_reviews},
         'offers':offers[:a.top],'all_count':len(offers),'pre_filter_count':pre,
         'raw_files':{'ggsel_json':str(gj),'ggsel_csv':str(gc),'plati_json':str(pj),'plati_csv':str(pc)}}
    if a.json:
        print(json.dumps(res,ensure_ascii=False,indent=2)); return
    if a.grouped:
        for d in ['own-login','own-no-login','ready-account','shared-account','unknown']:
            g=[o for o in offers if o.get('delivery')==d][:a.top]
            if not g: continue
            print(f"\n## {d} ({len(g)})")
            for i,o in enumerate(g,1):
                print(_fmt_row(i,o))
        print('\nRaw files:')
        for k, v in res['raw_files'].items():
            print(f'  {k}: {v}')
        return
    print(f'Top {a.top} offers for purpose={a.purpose} delivery={a.delivery}:')
    for i,o in enumerate(res['offers'],1):
        print(_fmt_row(i,o))
    print('\nRaw files:')
    for k, v in res['raw_files'].items():
        print(f'  {k}: {v}')

if __name__=='__main__': main()
