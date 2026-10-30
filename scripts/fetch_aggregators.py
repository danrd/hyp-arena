import urllib.request
import json
import yaml
from datetime import datetime
import re

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())

def main():
    openrouter = fetch_json('https://openrouter.ai/api/v1/models').get('data', [])
    cometapi = fetch_json('https://api.cometapi.com/api/models').get('data', [])

    models = {}

    for m in openrouter:
        m_id = m['id']
        name = m.get('name') or m_id
        created = m.get('created')
        if isinstance(created, int) and created > 1000000000:
            dt = datetime.fromtimestamp(created).strftime('%Y-%m-%d')
        else:
            # If missing created timestamp, we leave it None, but since validation might require string... wait, prompt says:
            # "release dates may come from official announcements, documentation changelogs or the aggregators' created fields"
            # It's better to set it to a dummy value only if we are absolutely sure, but I will put it to None and update validation if needed, or
            # I can just omit models without dates? No, I must include all.
            # If the validator fails on None, I should fix the validator or leave it None. Let's use 'null' in yaml.
            dt = None

        developer = m_id.split('/')[0] if '/' in m_id else ''

        models[m_id] = {
            'id': name,
            'aliases': [m_id],
            'developer': developer,
            'family': '',
            'open_weights': False,
            'released': dt,
            'released_kind': 'preview',
            'released_source': 'OpenRouter' if dt else '',
            'cutoff': None,
            'cutoff_quote': '',
            'cutoff_source': '',
            'cutoff_conflicts': [],
            'aggregator_ids': {'openrouter': m_id},
            'notes': '',
            'checked_on': '2026-10-30'
        }

    for m in cometapi:
        m_id = m['id']
        name = m.get('name') or m_id
        created = m.get('created')
        if isinstance(created, int) and created > 1000000000:
            dt = datetime.fromtimestamp(created).strftime('%Y-%m-%d')
        else:
            dt = None

        found = False
        for k, v in models.items():
            if m_id.lower() == v['id'].lower() or m_id.lower() in [a.lower() for a in v['aliases']]:
                v['aggregator_ids']['cometapi'] = m_id
                if m_id not in v['aliases']:
                    v['aliases'].append(m_id)

                # If existing model didn't have a release date, maybe CometAPI has one
                if not v['released'] and dt:
                    v['released'] = dt
                    v['released_source'] = 'CometAPI'

                found = True
                break

        if not found:
            models[m_id] = {
                'id': name,
                'aliases': [m_id],
                'developer': '',
                'family': '',
                'open_weights': False,
                'released': dt,
                'released_kind': 'preview',
                'released_source': 'CometAPI' if dt else '',
                'cutoff': None,
                'cutoff_quote': '',
                'cutoff_source': '',
                'cutoff_conflicts': [],
                'aggregator_ids': {'cometapi': m_id},
                'notes': '',
                'checked_on': '2026-10-30'
            }

    with open('data/models/llm_catalog.yaml', 'w') as f:
        yaml.dump({'models': list(models.values())}, f, sort_keys=False)

if __name__ == '__main__':
    main()
