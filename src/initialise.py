'''
This file handles setting the initial train states provided by NationalRail daily, at approx. 4am.
Files are served via xml, containing `_ref_v4.xml` and `_v8.xml`, ref contains location references
and the v8 contains the actual data.
'''

import argparse
import logging
import re
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from os import listdir
from os.path import isfile, join

from lxml import etree

from config import load_config
from darwin import SCHEDULE_STOP_TYPES, Schedule, ScheduleStop
from db import Database
from util import LONDON, convert_to_bool, parse_time

logger = logging.getLogger("initialise")


def get_latest(data_dir: str, ref: bool = False) -> str | None:
    files = [f for f in listdir(data_dir) if isfile(join(data_dir, f))]

    suffix = "_ref_v4" if ref else "_v8"
    pattern = re.compile(rf'PPTimetable_(\d{{14}}){suffix}\.xml')

    latest_date = None
    latest_file = None

    for file in files:
        match = pattern.fullmatch(file)
        if not match:
            continue
        date = int(match.group(1))
        if not latest_date or date > latest_date:
            latest_date = date
            latest_file = file

    return join(data_dir, latest_file) if latest_file else None

def fetch_ref_data(data_dir: str):
    loc_refs = {}
    toc_refs = {}
    late_reasons = {}
    cancellation_reasons = {}
    via = {}
    cis = {}
    loading = {}

    ref_file = get_latest(data_dir=data_dir, ref=True)
    if not ref_file:
        raise FileNotFoundError(f"No reference file in {data_dir}")

    logger.info("Reading reference data from %s", ref_file)
    tree = etree.parse(ref_file)
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

def parse_journey(journey: etree._Element) -> Schedule:
    """Turn a timetable `Journey` element into a Schedule. The XML keeps stops in calling order."""
    stops = []
    cancel_reason = None

    for stop in journey:
        tag = etree.QName(stop).localname

        if tag == "cancelReason":
            cancel_reason = stop.text
            continue
        if tag not in SCHEDULE_STOP_TYPES:
            continue

        # OR - Passenger Origin Calling Point (Where the train starts)
        # PP - Intermediate Passing Point (What the train will go past, not stop at)
        # IP - Intermediate Calling Location (Where the train will stop)
        # DT - Passenger Destination Calling point (The final destination)
        # OP* - The operational (non-passenger) equivalents
        stops.append(ScheduleStop(
            tiploc=stop.get('tpl'),
            location_type=tag,
            activities=stop.get('act'),
            planned_activities=stop.get('planAct'),
            cancelled=convert_to_bool(stop.get('can'), False),
            platform=stop.get('plat'),
            public_arrival=stop.get('pta'),
            public_departure=stop.get('ptd'),
            working_arrival=stop.get('wta'),
            working_departure=stop.get('wtd'),
            working_pass=stop.get('wtp'),
        ))

    return Schedule(
        rid=journey.get('rid'),
        uid=journey.get('uid'),
        train_id=journey.get('trainId'),
        scheduled_start=journey.get('ssd'),
        toc=journey.get('toc'),
        status=journey.get('status'),
        category=journey.get('trainCat'),
        is_passenger=convert_to_bool(journey.get('isPassengerSvc'), True),
        cancelled=convert_to_bool(journey.get('can'), False),
        deleted=convert_to_bool(journey.get('deleted'), False),
        cancel_reason=int(cancel_reason) if cancel_reason and cancel_reason.isdigit() else None,
        stops=stops,
    )


def fetch_initial_journeys(data_dir: str) -> list[Schedule]:
    journeys_file = get_latest(data_dir=data_dir, ref=False)
    if not journeys_file:
        raise FileNotFoundError(f"No journeys file in {data_dir}")

    logger.info("Reading journeys from %s", journeys_file)
    tree = etree.parse(journeys_file)
    root: etree._Element = tree.getroot()

    schedules = []
    for child in root:
        tag = etree.QName(child).localname

        if tag == "Journey":
            schedules.append(parse_journey(child))
        elif tag == "Association":
            # ToDo: implement associations
            pass

    return schedules


def run(db: Database, data_dir: str):
    data = fetch_ref_data(data_dir)

    start = time.time()
    logger.info("Started ref init")

    db.add_code_maps(table='train_operator_codes', key_col='toc', value_col='name', code_map=data['toc_refs'])
    db.add_code_maps(table='cis_codes', key_col='code', value_col='name', code_map=data['cis_source'])
    db.add_code_maps(table='late_reasons', key_col='code', value_col='reason', code_map=data['late_reasons'])
    db.add_code_maps(table='cancellation_reasons', key_col='code', value_col='reason', code_map=data['cancellation_reasons'])
    db.add_location_refs(data['location_refs'].items())

    logger.info("Finished ref init (%.1fs)", time.time() - start)

    schedules = fetch_initial_journeys(data_dir)

    start = time.time()
    logger.info("Started journey init (%d journeys)", len(schedules))
    db.add_schedules(schedules)
    logger.info("Finished journey init (%.1fs)", time.time() - start)


def seconds_until(at: dtime) -> float:
    now = datetime.now(LONDON)
    target = datetime.combine(now.date(), at, tzinfo=LONDON)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main():
    parser = argparse.ArgumentParser(description="Load the Darwin timetable files into the database")
    parser.add_argument("--daily", metavar="HH:MM",
                        help="keep running and reload every day at this UK time (the files arrive at about 04:00)")
    args = parser.parse_args()

    config = load_config()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(config.database_url)

    try:
        run(db, config.data_dir)
        if args.daily:
            at = parse_time(args.daily)
            if at is None:
                raise SystemExit(f"--daily expects HH:MM, got {args.daily!r}")
            while True:
                wait = seconds_until(at)
                logger.info("Next timetable load in %.0f minutes", wait / 60)
                time.sleep(wait)
                try:
                    run(db, config.data_dir)
                except Exception:
                    logger.exception("Timetable load failed, will retry tomorrow")
    finally:
        db.close()


if __name__ == "__main__":
    main()
