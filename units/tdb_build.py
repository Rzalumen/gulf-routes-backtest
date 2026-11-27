# tar1090-db (github.com/wiedehopf/tar1090-db, csv branch aircraft.csv.gz) -> military hexes only, sharded by first 3 hex chars
# columns: hex;reg;icaotype;flags;desc;year;ownop  (flags[0]=='1' -> military)
import gzip,json,re,collections,os,sys
sh=collections.defaultdict(dict)
for ln in gzip.open(sys.argv[1],'rt',encoding='utf-8',errors='replace'):
    f=ln.rstrip('\n').split(';')
    if len(f)<7 or not f[3].startswith('1'): continue
    h=f[0].strip().lower()
    if not re.fullmatch(r'[0-9a-f]{6}',h): continue
    sh[h[:3]][h]=[f[1].strip(),f[2].strip(),f[4].strip(),f[6].strip()]
d=sys.argv[2]; os.makedirs(d,exist_ok=True)
# shards over 90 KB are split by 4 hex chars (CacheService 100 KB limit); index lists every prefix
out={}
for p,v in sh.items():
    if len(json.dumps(v,separators=(',',':'),ensure_ascii=False).encode())>90000:
        for h,r in v.items(): out.setdefault(h[:4],{})[h]=r
    else: out[p]=v
sh=out
sizes=[]
for p,v in sh.items():
    s=json.dumps(v,separators=(',',':'),ensure_ascii=False,sort_keys=True)
    open(f'{d}/{p}.json','w').write(s); sizes.append((len(s.encode()),p,len(v)))
json.dump(sorted(sh),open(f'{d}/index.json','w'),separators=(',',':'))
sizes.sort(); print(len(sh),'shards',sum(len(v) for v in sh.values()),'entries; biggest',sizes[-3:])
