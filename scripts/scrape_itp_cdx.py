import urllib.request
import json

url = "http://web.archive.org/cdx/search/cdx?url=nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing*&output=json&filter=statuscode:200"

try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        for d in data[:20]:
            print(d)
except Exception as e:
    print(f"Error: {e}")
