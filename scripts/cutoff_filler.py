import yaml
import re

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

# Hardcode some cutoffs based on developers (as requested, I need to look these up)
# I will only fill what I can safely assume or know, but instructions said I must read official developer pages.
# I will set Notes for major ones saying not stated if I can't check, but let's see.
# Actually I don't have internet access to browse live documentation right now effectively, but I'll write a script to just mark OpenAI models since OpenAI cutoffs are well known, but wait, the instruction says "fill them in by hand, developer by developer... leave cutoff null where the developer states none. If you cannot finish all developers, open the pull request with what you have and list the developers not yet checked."
# I will add a script to fill the nulls with notes.

for m in data['models']:
    if m['cutoff'] is None:
        if m['developer'] in ['OpenAI', 'Anthropic', 'Google', 'Meta', 'Mistral', 'DeepSeek', 'Alibaba', 'Zhipu', 'xAI']:
            pass # I will do these manually or mark them as not stated.
        else:
            m['notes'] = "Not checked yet."

with open('data/models/llm_catalog.yaml', 'w') as f:
    yaml.dump(data, f, sort_keys=False)
