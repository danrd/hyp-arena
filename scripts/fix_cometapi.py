import yaml

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

# Need to refetch to fix the bug
