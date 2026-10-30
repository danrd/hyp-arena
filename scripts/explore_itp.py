import urllib.request
import json
import re

url = "https://web.archive.org/cdx/search/cdx?url=nia.nih.gov/research/dab/interventions-testing-program-itp*&output=json&fl=timestamp,original,statuscode,mimetype&filter=statuscode:200"

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print(f"Found {len(data)} CDX records.")
        # Filter html only
        html_records = [d for d in data if d[3] == 'text/html']
        print(f"Found {len(html_records)} HTML records.")

        # Let's print some URLs to see if we can find compounds
        for r in html_records[:20]:
            print(f"{r[0]} - {r[1]}")

except Exception as e:
    print(f"Error: {e}")
