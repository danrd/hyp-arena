import urllib.request
import json
import re

url = "http://web.archive.org/cdx/search/cdx?url=nia.nih.gov/research/dab/interventions-testing-program-itp*&output=json&filter=statuscode:200"

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        html_records = [d for d in data if d[3] == 'text/html']

        # Take a subset of records, spaced out to not overwhelm
        timestamps_to_check = [d[1] for d in html_records[:5]]
        for ts in timestamps_to_check:
            print(f"Fetching https://web.archive.org/web/{ts}/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp")
            try:
                page_url = f"https://web.archive.org/web/{ts}/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp"
                req2 = urllib.request.Request(page_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req2) as resp:
                    html = resp.read().decode(errors='ignore')
                    # check for compounds/rationale
                    if 'compound' in html.lower() or 'rationale' in html.lower() or 'testing' in html.lower():
                        print("Found interesting keywords!")
            except Exception as e:
                print(f"Error fetching {ts}: {e}")

except Exception as e:
    print(f"Error: {e}")
