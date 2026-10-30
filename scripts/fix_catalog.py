import yaml

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

for m in data['models']:
    # Clean up developer names
    dev = m.get('developer', '')
    if dev:
        if 'openai' in dev.lower(): m['developer'] = 'OpenAI'
        elif 'anthropic' in dev.lower(): m['developer'] = 'Anthropic'
        elif 'google' in dev.lower(): m['developer'] = 'Google'
        elif 'meta' in dev.lower(): m['developer'] = 'Meta'
        elif 'mistral' in dev.lower(): m['developer'] = 'Mistral'
        elif 'deepseek' in dev.lower(): m['developer'] = 'DeepSeek'
        elif 'qwen' in dev.lower() or 'alibaba' in dev.lower(): m['developer'] = 'Alibaba'
        elif 'zhipu' in dev.lower() or 'glm' in dev.lower(): m['developer'] = 'Zhipu'
        elif 'xai' in dev.lower(): m['developer'] = 'xAI'
        elif 'moonshot' in dev.lower(): m['developer'] = 'Moonshot'
        elif 'microsoft' in dev.lower(): m['developer'] = 'Microsoft'
        elif 'cohere' in dev.lower(): m['developer'] = 'Cohere'
        elif 'ai21' in dev.lower(): m['developer'] = 'AI21'
        elif 'amazon' in dev.lower(): m['developer'] = 'Amazon'
        elif 'nvidia' in dev.lower(): m['developer'] = 'NVIDIA'
        elif 'minimax' in dev.lower(): m['developer'] = 'MiniMax'
        elif '01.ai' in dev.lower(): m['developer'] = '01.AI'
        elif 'baidu' in dev.lower(): m['developer'] = 'Baidu'
        elif 'tencent' in dev.lower(): m['developer'] = 'Tencent'
        elif 'bytedance' in dev.lower() or 'doubao' in dev.lower() or 'seed' in dev.lower(): m['developer'] = 'ByteDance'

    # Try setting family
    name = m.get('id', '').lower()
    m_id = m.get('aliases', [''])[0].lower()
    if 'gpt' in name or 'o1' in name or 'o3' in name: m['family'] = 'GPT/O'
    elif 'claude' in name: m['family'] = 'Claude'
    elif 'gemini' in name or 'gemma' in name: m['family'] = 'Gemini/Gemma'
    elif 'llama' in name: m['family'] = 'Llama'
    elif 'mistral' in name or 'mixtral' in name: m['family'] = 'Mistral'
    elif 'deepseek' in name: m['family'] = 'DeepSeek'
    elif 'qwen' in name: m['family'] = 'Qwen'

    # open_weights bug fix
    m['open_weights'] = False
    if m['family'] in ['Llama', 'Gemma', 'Qwen']:
        m['open_weights'] = True
    elif ('open' in m_id or 'instruct' in m_id) and ('openai' not in dev.lower() and 'anthropic' not in dev.lower() and 'google' not in dev.lower()):
        m['open_weights'] = True

with open('data/models/llm_catalog.yaml', 'w') as f:
    yaml.dump(data, f, sort_keys=False)
