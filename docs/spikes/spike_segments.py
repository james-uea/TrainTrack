import gzip, json, numpy as np, shapefile
import xml.etree.ElementTree as ET
from scipy.spatial import cKDTree
from collections import Counter
UP='/mnt/user-data/uploads/TrainTrack/data/'
CALL={'OR','IP','DT','OPOR','OPIP','OPDT'}
bp={}
for line in gzip.open(UP+'bplan/PIF20261120571120089.txt.gz','rt',encoding='latin-1'):
    if line.startswith('LOC'):
        f=line.split('\t')
        try: e,n=int(f[6] or 0),int(f[7] or 0)
        except: continue
        if 0<e<700000 and 0<n<1300000: bp[f[2]]=(e,n)
pts=[]
for s in shapefile.Reader('data/tm/NWR_TrackCentreLines').iterShapes(): pts.extend(s.points)
tree=cKDTree(np.array(pts))
keys=list(bp); d,_=tree.query(np.array([bp[k] for k in keys]))
good={k for k,x in zip(keys,d) if x<=500}
far2k={k for k,x in zip(keys,d) if x>2000}
seg_ok=seg_tot=0; jall=jtot=0; pax_seg_ok=pax_seg_tot=0
for ev,el in ET.iterparse(gzip.open(UP+'PPTimetable_20261121020530_v8.xml.gz'),events=('end',)):
    if not el.tag.endswith('Journey'): continue
    calls=[c.get('tpl') for c in el if c.tag.split('}')[1] in CALL]
    pax = el.get('isPassengerSvc')!='false'
    jtot+=1; jall+= all(c in good for c in calls)
    for a,b in zip(calls,calls[1:]):
        ok = a in good and b in good
        seg_tot+=1; seg_ok+=ok
        if pax: pax_seg_tot+=1; pax_seg_ok+=ok
    el.clear()
print(json.dumps({'good_within_500m':len(good),'bplan_valid':len(bp),'call_segments_both_ends_good':f'{100*seg_ok/seg_tot:.1f}%','pax_call_segments_both_good':f'{100*pax_seg_ok/pax_seg_tot:.1f}%','journeys_all_calls_good':f'{100*jall/jtot:.1f}%'},indent=1))
