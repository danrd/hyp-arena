import urllib.request
import json
import time

url = "http://web.archive.org/cdx/search/cdx?url=nia.nih.gov/research/dab/interventions-testing-program-itp*&output=json&filter=statuscode:200"

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())

        # Look for any page that might have rationale
        urls = set([d[2] for d in data if d[3] == 'text/html'])
        print(f"Total unique URLs: {len(urls)}")
        for u in sorted(list(urls)):
            print(u)
except Exception as e:
    print(f"Error: {e}")
