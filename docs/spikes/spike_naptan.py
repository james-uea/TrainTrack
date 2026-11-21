import gzip, csv, json, numpy as np, shapefile
import xml.etree.ElementTree as ET
from scipy.spatial import cKDTree
from collections import Counter
UP='/mnt/user-data/uploads/TrainTrack/data/'
CALL={'OR','IP','DT','OPOR','OPIP','OPDT'}
ok=lambda e,n: 0<e<700000 and 0<n<1300000
bp={}
for line in gzip.open(UP+'bplan/PIF20261120571120089.txt.gz','rt',encoding='latin-1'):
    if line.startswith('LOC'):
        f=line.split('\t')
        try: e,n=int(f[6] or 0),int(f[7] or 0)
        except: continue
        if ok(e,n): bp[f[2]]=(e,n)
nap={}; status=Counter()
with open(UP+'naptan/Stops.csv',encoding='utf-8',errors='replace') as fh:
    for r in csv.DictReader(fh):
        if r['StopType']=='RLY' and r['ATCOCode'].startswith('9100'):
            status[r['Status']]+=1
            try: e,n=float(r['Easting']),float(r['Northing'])
            except: continue
            if ok(e,n): nap[r['ATCOCode'][4:]]=(e,n)
pts=[]
for s in shapefile.Reader('data/tm/NWR_TrackCentreLines').iterShapes(): pts.extend(s.points)
tree=cKDTree(np.array(pts))
def good_set(src):
    k=list(src); d,_=tree.query(np.array([src[x] for x in k])); return {a:x for a,x in zip(k,d)}
dbp=good_set(bp); dnap=good_set(nap)
# combined: NaPTAN first for stations if within 500m (or if not NR track, accept anyway), else BPLAN within 500m
comb={}
for k,v in bp.items():
    if dbp[k]<=500: comb[k]=v
for k,v in nap.items():
    if dnap[k]<=500 or k not in comb: comb[k]=v   # NaPTAN trusted for stations, even off NR track (EL core, ELL)
occ=Counter(); occ_call=Counter()
seg=Counter(); jall=jtot=0
for ev,el in ET.iterparse(gzip.open(UP+'PPTimetable_20261121020530_v8.xml.gz'),events=('end',)):
    if not el.tag.endswith('Journey'): continue
    calls=[]
    for c in el:
        t=c.tag.split('}')[1]; tpl=c.get('tpl')
        if not tpl: continue
        occ[tpl]+=1
        if t in CALL: calls.append(tpl); occ_call[tpl]+=1
    pax=el.get('isPassengerSvc')!='false'
    jtot+=1; jall+=all(c in comb for c in calls)
    for a,b in zip(calls,calls[1:]):
        seg['tot']+=1; seg['ok']+=(a in comb and b in comb)
        if pax: seg['ptot']+=1; seg['pok']+=(a in comb and b in comb)
    el.clear()
W=sum(occ.values()); Wc=sum(occ_call.values())
miss=sorted(((occ_call[k],k) for k in occ_call if k not in comb),reverse=True)
naparr=np.array([dnap[k] for k in occ if k in nap])
both=[np.hypot(bp[k][0]-nap[k][0],bp[k][1]-nap[k][1]) for k in occ if k in bp and k in nap]
print(json.dumps({
 'naptan_rail_stops':len(nap),'naptan_status':status,
 'naptan_tiplocs_used_today':sum(1 for k in occ if k in nap),
 'naptan_dist_to_track_m':{q:round(float(np.percentile(naparr,q)),1) for q in (50,90,99)},
 'naptan_vs_bplan_m':{q:round(float(np.percentile(both,q)),1) for q in (50,90,99)},
 'combined_tiplocs':f"{sum(1 for k in occ if k in comb)}/{len(occ)}",
 'combined_train_stops':f"{100*sum(v for k,v in occ.items() if k in comb)/W:.1f}%",
 'combined_calls':f"{100*sum(v for k,v in occ_call.items() if k in comb)/Wc:.1f}%",
 'call_segments_ok':f"{100*seg['ok']/seg['tot']:.1f}%",'pax_call_segments_ok':f"{100*seg['pok']/seg['ptot']:.1f}%",
 'journeys_all_calls':f"{100*jall/jtot:.1f}%",
 'missing_calls_top20':miss[:20]},indent=1,default=str))
