import csv,json,re,collections,os,sys
r=list(csv.DictReader(open(sys.argv[1],encoding='utf-8')))
sh=collections.defaultdict(dict)
for x in r:
    if x['#CMPG'] not in ('Mil','Gov'): continue
    h=x['$ICAO'].strip().lower()
    if not re.fullmatch(r'[0-9a-f]{6}',h): continue
    sh[h[:3]][h]=[x['$Registration'].strip(),x['$Operator'].strip(),x['$ICAO Type'].strip(),x['$Tag 1'].strip(),x['Category'].strip()]
d=sys.argv[2]; os.makedirs(d,exist_ok=True)
sizes=[]
for p,v in sh.items():
    s=json.dumps(v,separators=(',',':'),ensure_ascii=False,sort_keys=True)
    open(f'{d}/{p}.json','w').write(s); sizes.append((len(s.encode()),p,len(v)))
json.dump(sorted(sh),open(f'{d}/index.json','w'),separators=(',',':'))
sizes.sort(); print(len(sh),'shards',sum(len(v) for v in sh.values()),'entries; biggest',sizes[-3:])
