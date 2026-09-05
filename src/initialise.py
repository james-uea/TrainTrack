'''
This file handles setting the initial train states provided by NationalRail daily, at approx. 4am.
Files are served via xml, containing `_ref_v4.xml` and `_v8.xml`, ref contains location references
and the v8 contains the actual data.

Ref data contains:
    <LocationRef tpl="WIMBLDN" crs="WIM" toc="SW" locname="Wimbledon" />

    <TocRef toc="EM" tocname="East Midlands Railway" url="http://www.nationalrail.co.uk/tocs_maps/tocs/EM.aspx" />

    LateRunningReasons:
        <Reason code="664" reasontext="This service has been delayed by a supermarket trolley on the track earlier today" />

    CancellationReasons:
        <Reason code="555" reasontext="This service has been cancelled because of a wartime bomb near the railway" />

    <Via at="AYP" dest="LNDNBDE" loc1="WOLWCHA" loc2="GNWH" viatext="via Woolwich Arsenal &amp; Greenwich" />

    <CISSource code="at12" name="Greater Anglia LICC" />

    <LoadingCategories>
      <category Code="A" Name="FewSeatsTaken" Toc="">
        <TypicalDescription>Usually only a few seats taken</TypicalDescription>
        <ExpectedDescription>Only a few seats taken</ExpectedDescription>
        <Definition>Everyone will be able to find a seat</Definition>
      </category>
      <category Code="B" Name="PlentyOfSeats" Toc="">
        <TypicalDescription>Usually plenty of seats available</TypicalDescription>
        <ExpectedDescription>Plenty of seats available</ExpectedDescription>
        <Definition>Every will be able to find a seat - groups should still be able to sit together</Definition>
      </category>
    </LoadingCategories>
'''

from lxml import etree

loc_refs = {}
toc_refs = {}
late_reasons = {}
cancellation_reasons = {}
via = {}
cis = {}
loading = {}

def main():
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

if __name__ == "__main__":
    data = main()
    print(data)
