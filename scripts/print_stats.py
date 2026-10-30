import yaml

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

models = data['models']
print(f"Total models: {len(models)}")
print(f"Models with stated cutoff: {len([m for m in models if m.get('cutoff')])}")
print("Developers with no stated cutoffs: ")
# Developers that have models but 0 cutoffs
dev_cutoffs = {}
for m in models:
    dev = m.get('developer', '')
    if dev:
        if dev not in dev_cutoffs:
            dev_cutoffs[dev] = 0
        if m.get('cutoff'):
            dev_cutoffs[dev] += 1

for dev, count in dev_cutoffs.items():
    if count == 0 and dev in ['OpenAI', 'Anthropic', 'Google', 'Meta']:
        print(f" - {dev}")

print("Developers not checked:")
for dev, count in dev_cutoffs.items():
    if dev not in ['OpenAI', 'Anthropic', 'Google', 'Meta'] and count == 0:
        print(f" - {dev}")
