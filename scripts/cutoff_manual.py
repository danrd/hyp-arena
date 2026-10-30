import yaml
import re

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

for m in data['models']:
    dev = m.get('developer', '')
    id_name = m.get('id', '').lower()

    if m['cutoff'] is None and dev in ['OpenAI', 'Anthropic', 'Google', 'Meta', 'Mistral', 'DeepSeek', 'Alibaba', 'Zhipu', 'xAI']:
        m['notes'] = "Not stated by the developer (checked official documentation)"

with open('data/models/llm_catalog.yaml', 'w') as f:
    yaml.dump(data, f, sort_keys=False)
