'''
This file handles setting the initial train states provided by NationalRail daily, at approx. 4am.
Files are served via xml, containing `_ref_v4.xml` and `_v8.xml`, ref contains location references
and the v8 contains the actual data.
'''

import sys
import time
from datetime import UTC, datetime

import psycopg
from lxml import etree

from db import Database
from util import convert_to_bool


def fetch_ref_data():
    loc_refs = {}
    toc_refs = {}
    late_reasons = {}
    cancellation_reasons = {}
    via = {}
    cis = {}
    loading = {}

    tree = etree.parse('data/PPTimetable_20260905020530_ref_v4.xml')
    root = tree.getroot()

    for child in root:
        tag = etree.QName(child).localname

        if tag == "LocationRef":
            tpl = child.get('tpl')
            if tpl:
                loc_refs[tpl] = {
                    'crs': child.get('crs'),
                    'toc': child.get('toc'),
                    'locname': child.get('locname')
                }
        elif tag == "TocRef":
            toc = child.get('toc')
            if toc:
                toc_refs[toc] = child.get('tocname')
        elif tag == "LateRunningReasons":
            for reason in child:
                code = reason.get('code')
                if code:
                    reason_text = reason.get('reasontext')
                    late_reasons[code] = reason_text
        elif tag == "CancellationReasons":
            for reason in child:
                code = reason.get('code')
                if code:
                    reason_text = reason.get('reasontext')
                    cancellation_reasons[code] = reason_text
        elif tag == "Via":
            # ToDo: Implement via
            pass
        elif tag == "CISSource":
            code = child.get('code')
            if code:
                cis[code] = child.get('name')

    return {
        'location_refs': loc_refs,
        'toc_refs': toc_refs,
        'late_reasons': late_reasons,
        'cancellation_reasons': cancellation_reasons,
        'via': via,
        'cis_source': cis,
        'loading_categories': loading
    }

def get_stops(rid, journey: etree._Element):
    stops = []
    cancel_reason = None

    for idx, stop in enumerate(journey):
        tag = etree.QName(stop).localname

        if tag == "cancelReason":
            cancel_reason = stop.text
            continue

        # tpl, act, planAct, can, plat, pta, ptd
        # OR - Passenger Origin Calling Point (Where the train starts)
        # PP - Intermediate Passing Point (What the train will go past, not stop at)
        # IP - Intermediate Calling Location (Where the train will stop)
        # DT - Passenger Destination Calling point (The final destination)

        stop_info = {
            'rid': rid,
            'sequence': idx,
            'tiploc': stop.get('tpl'),
            'activities': stop.get('act'),
            'planned_activities': stop.get('planAct'),
            'cancelled': convert_to_bool(stop.get('can'), False),
            'platform': stop.get('plat'),
            'public_arrival': stop.get('pta'),
            'public_departure': stop.get('ptd'),
            'working_arrival': stop.get('wta'),
            'working_departure': stop.get('wtd'),
            'working_pass': stop.get('wtp'),
            'location_type': tag
        }

        stops.append(stop_info)

    return stops, cancel_reason

def fetch_initial_journeys():
    tree = etree.parse('data/PPTimetable_20260905020530_v8.xml')
    root: etree._Element = tree.getroot()

    journeys = {}
    associations = {}

    for child in root:
        tag = etree.QName(child).localname

        if tag == "Journey":
            rid = child.get('rid')

            stops, cancel_reason = get_stops(rid, child)

            journeys[rid] = {
                'uid' : child.get('uid'),
                'train_id' : child.get('trainId'),
                'ssd' : child.get('ssd'),
                'toc' : child.get('toc'),
                'status' : child.get('status'),
                'category' : child.get('trainCat'),
                'passenger_service' : child.get('isPassengerSvc'),
                'deleted' : child.get('deleted'),
                'cancelled' : child.get('can'),
                'cancel_reason' : cancel_reason,
                'stops': stops
            }

        elif tag == "Association":
            # ToDo: implement associations
            pass

    return journeys, associations

def add_train_journeys(db: Database, journeys, assosiations):
    db.add_train_journeys(list(journeys.items()))
    db.add_train_stops(
        stop
        for journey in journeys.values()
        for stop in journey["stops"]
    )

if __name__ == "__main__":
    db = Database()
    data = fetch_ref_data()

    start = time.time()
    start_dt = datetime.fromtimestamp(start, UTC)
    print(f"Started ref init @ {start_dt}")

    db.add_code_maps(table='train_operator_codes', key_col='toc', value_col='name', code_map=data['toc_refs'])
    db.add_code_maps(table='cis_codes', key_col='code', value_col='name', code_map=data['cis_source'])
    db.add_code_maps(table='late_reasons', key_col='code', value_col='reason', code_map=data['late_reasons'])
    db.add_code_maps(table='cancellation_reasons', key_col='code', value_col='reason', code_map=data['cancellation_reasons'])

    db.add_location_refs(data['location_refs'].items())
    db.commit()

    end = time.time()
    end_dt = datetime.fromtimestamp(end, UTC)
    delta = end-start

    print(f"Finished ref init @ {end_dt} ({delta}s)")

    journies, assosiations = fetch_initial_journeys()

    start = time.time()
    start_dt = datetime.fromtimestamp(start, UTC)
    print(f"Started journey init @ {start_dt}")

    add_train_journeys(db, journies, assosiations)

    db.commit()

    end = time.time()
    end_dt = datetime.fromtimestamp(end, UTC)
    delta = end-start

    print(f"Finished journey init @ {end_dt} ({delta}s)")

    db.close()
