import yaml
import sys
import re

def check_catalog(filepath):
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"Failed to load yaml: {e}")
        return False

    models = data.get('models', [])
    if not isinstance(models, list):
        print("models is not a list")
        return False

    required_fields = ['id', 'aliases', 'developer', 'family', 'open_weights',
                       'released', 'released_kind', 'released_source',
                       'cutoff', 'cutoff_quote', 'cutoff_source',
                       'cutoff_conflicts', 'aggregator_ids', 'notes', 'checked_on']

    date_regex = re.compile(r'^(\d{4}|\d{4}-\d{2}|\d{4}-\d{2}-\d{2})$')

    for m in models:
        for f in required_fields:
            if f not in m:
                print(f"Missing field {f} in model {m.get('id')}")
                return False

        if m['released'] is not None:
            if not date_regex.match(str(m['released'])):
                print(f"Invalid released date format in model {m.get('id')}: {m['released']}")
                return False
            if not m['released_source']:
                print(f"Missing released_source in model {m.get('id')}")
                return False

        if m['cutoff'] is not None:
            if not date_regex.match(str(m['cutoff'])):
                print(f"Invalid cutoff date format in model {m.get('id')}: {m['cutoff']}")
                return False
            if not m['cutoff_quote']:
                print(f"Missing cutoff_quote when cutoff is set in model {m.get('id')}")
                return False
            if not m['cutoff_source']:
                print(f"Missing cutoff_source when cutoff is set in model {m.get('id')}")
                return False

    print("Catalog check passed.")
    return True

if __name__ == '__main__':
    if not check_catalog('data/models/llm_catalog.yaml'):
        sys.exit(1)
