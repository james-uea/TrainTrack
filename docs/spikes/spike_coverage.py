"""Milestone 2 data spike: how many timetable TIPLOCs can we place on the map?"""
import gzip, re, sys, json
from collections import Counter, defaultdict
import xml.etree.ElementTree as ET
import numpy as np, shapefile
from scipy.spatial import cKDTree

UP = '/mnt/user-data/uploads/TrainTrack/data/'
TT = UP + 'PPTimetable_20261121020530_v8.xml.gz'
REF = UP + 'PPTimetable_20261121020530_ref_v4.xml.gz'
BPLAN = UP + 'bplan/PIF20261120571120089.txt.gz'
TPNM = 'data/tpnm/XML_p.xml'
TM = 'data/tm/'

CALL = {'OR', 'IP', 'DT', 'OPOR', 'OPIP', 'OPDT'}

def valid(e, n):
    return 0 < e < 700000 and 0 < n < 1300000

# 1. Timetable usage: occurrences per TIPLOC, passenger trains only and all
occ_all, occ_call, occ_pass = Counter(), Counter(), Counter()
journeys = pax = 0
for ev, el in ET.iterparse(gzip.open(TT), events=('end',)):
    tag = el.tag.split('}')[1]
    if tag != 'Journey':
        continue
    journeys += 1
    if el.get('isPassengerSvc') != 'false':
        pax += 1
    for c in el:
        t = c.tag.split('}')[1]
        tpl = c.get('tpl')
        if not tpl:
            continue
        occ_all[tpl] += 1
        (occ_call if t in CALL else occ_pass)[tpl] += 1
    el.clear()

names = {}
for ev, el in ET.iterparse(gzip.open(REF), events=('end',)):
    if el.tag.endswith('LocationRef'):
        names[el.get('tpl')] = el.get('locname')
    el.clear()

# 2. BPLAN LOC coordinates
bplan, bplan_name, bplan_tptype = {}, {}, {}
bplan_all = set()
for line in gzip.open(BPLAN, 'rt', encoding='latin-1'):
    if not line.startswith('LOC'):
        continue
    f = line.rstrip('\n').split('\t')
    tpl = f[2]
    bplan_all.add(tpl)
    bplan_name[tpl] = f[3]
    bplan_tptype[tpl] = f[8]
    try:
        e, n = int(f[6] or 0), int(f[7] or 0)
    except ValueError:
        continue
    if valid(e, n):
        bplan[tpl] = (e, n)

# 3. TPNM station coordinates (by abbrev = TIPLOC)
tpnm = {}
pat = re.compile(r'<station [^>]*?abbrev="([^"]*)"[^>]*?easting="(\d+)" northing="(\d+)"')
with open(TPNM, encoding='latin-1') as fh:
    for line in fh:
        if line.startswith('<station '):
            m = pat.search(line)
            if m:
                e, n = int(m.group(2)), int(m.group(3))
                if valid(e, n):
                    tpnm[m.group(1)] = (e, n)

# 4. Track Model vertices
pts = []
r = shapefile.Reader(TM + 'NWR_TrackCentreLines')
for s in r.iterShapes():
    pts.extend(s.points)
pts = np.array(pts)
tree = cKDTree(pts)

def dist(xy):
    return tree.query(xy)[0]

used = set(occ_all)
def cov(src, counter):
    keys = set(counter)
    d = sum(1 for k in keys if k in src)
    w = sum(v for k, v in counter.items() if k in src)
    return d, len(keys), w, sum(counter.values())

both = dict(tpnm); both.update(bplan)
out = {'journeys': journeys, 'passenger_journeys': pax,
       'track_vertices': len(pts)}
for label, src in [('bplan', bplan), ('tpnm', tpnm), ('bplan_or_tpnm', both)]:
    for cl, ctr in [('all', occ_all), ('calls', occ_call), ('passes', occ_pass)]:
        d, D, w, W = cov(src, ctr)
        out[f'{label}_{cl}'] = f'{d}/{D} tiplocs ({100*d/D:.1f}%), {100*w/W:.1f}% of train-stops'

# distance from track for BPLAN points used today
dists = {k: dist(bplan[k]) for k in used if k in bplan}
arr = np.array(list(dists.values()))
out['bplan_dist_to_track_m'] = {q: round(float(np.percentile(arr, q)), 1) for q in (50, 90, 95, 99)}
out['bplan_over_500m'] = int((arr > 500).sum())
out['bplan_over_2km'] = int((arr > 2000).sum())
far = sorted(((v, k) for k, v in dists.items() if v > 500), reverse=True)
out['worst_far'] = [(k, bplan_name.get(k), int(v), occ_all[k]) for v, k in far[:15]]

# agreement between BPLAN and TPNM where both exist
diffs = [np.hypot(bplan[k][0]-tpnm[k][0], bplan[k][1]-tpnm[k][1]) for k in used if k in bplan and k in tpnm]
out['bplan_vs_tpnm_m'] = {q: round(float(np.percentile(diffs, q)), 1) for q in (50, 90, 99)} if diffs else None

missing = [(k, occ_all[k], occ_call[k], bplan_name.get(k) or names.get(k), k in bplan_all, bplan_tptype.get(k))
           for k in used if k not in both]
missing.sort(key=lambda x: -x[1])
out['missing_count'] = len(missing)
out['missing_not_in_bplan_at_all'] = sum(1 for m in missing if not m[4])
out['missing_top30'] = missing[:30]
json.dump(out, sys.stdout, indent=1, default=str)
