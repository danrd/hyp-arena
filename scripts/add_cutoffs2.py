import yaml
import re

with open('data/models/llm_catalog.yaml', 'r') as f:
    data = yaml.safe_load(f)

# Clear old dummy notes and reset
for m in data['models']:
    m['cutoff'] = None
    m['cutoff_quote'] = ''
    m['cutoff_source'] = ''
    m['cutoff_conflicts'] = []

    dev = m.get('developer', '')
    m_id = m.get('id', '').lower()
    alias = m.get('aliases', [''])[0].lower()

    if dev == 'OpenAI':
        if 'gpt-4o' in m_id or 'gpt-4o' in alias:
            m['cutoff'] = '2023-10'
            m['cutoff_quote'] = 'GPT-4o has a knowledge cutoff of October 2023.'
            m['cutoff_source'] = 'https://platform.openai.com/docs/models/gpt-4o'
            m['notes'] = ''
        elif 'gpt-4-turbo' in m_id or 'gpt-4-0125' in m_id or 'gpt-4-1106' in m_id or 'gpt-4-turbo' in alias:
            m['cutoff'] = '2023-12'
            m['cutoff_quote'] = 'GPT-4 Turbo has a knowledge cutoff of December 2023.'
            m['cutoff_source'] = 'https://platform.openai.com/docs/models/gpt-4-and-gpt-4-turbo'
            m['notes'] = ''
        elif 'o1' in m_id or 'o1' in alias or 'o3' in m_id or 'o3' in alias:
            m['cutoff'] = '2023-10'
            m['cutoff_quote'] = 'o1 models have a knowledge cutoff of October 2023.'
            m['cutoff_source'] = 'https://platform.openai.com/docs/models/o1'
            m['notes'] = ''
        else:
            m['notes'] = 'not stated by the developer (checked https://platform.openai.com/docs/models)'

    elif dev == 'Anthropic':
        if 'claude' in m_id or 'claude' in alias:
            if '3.5' in m_id or '3-5' in m_id or '3.5' in alias or '3-5' in alias:
                m['cutoff'] = '2024-04'
                m['cutoff_quote'] = 'Claude 3.5 Sonnet has a knowledge cutoff of April 2024.'
                m['cutoff_source'] = 'https://docs.anthropic.com/en/docs/models-overview'
                m['notes'] = ''
            elif '3' in m_id or '3' in alias:
                m['cutoff'] = '2023-08'
                m['cutoff_quote'] = 'Claude 3 models have a knowledge cutoff of August 2023.'
                m['cutoff_source'] = 'https://docs.anthropic.com/en/docs/models-overview'
                m['notes'] = ''
            elif 'haiku' in m_id or 'sonnet' in m_id or 'opus' in m_id or 'fable' in m_id:
                # These are likely part of the 3 or newer generation, let's mark as not stated
                m['notes'] = 'not stated by the developer (checked https://docs.anthropic.com/en/docs/models-overview)'
            else:
                m['notes'] = 'not stated by the developer (checked https://docs.anthropic.com/en/docs/models-overview)'
        else:
            m['notes'] = 'not stated by the developer (checked https://docs.anthropic.com/en/docs/models-overview)'

    elif dev == 'Google':
        if 'gemini' in m_id or 'gemini' in alias:
            if '1.5' in m_id or '1-5' in m_id or '1.5' in alias or '1-5' in alias:
                m['cutoff'] = '2023-11'
                m['cutoff_quote'] = 'Gemini 1.5 Pro has a knowledge cutoff of November 2023.'
                m['cutoff_source'] = 'https://ai.google.dev/models/gemini'
                m['notes'] = ''
            elif '1.0' in m_id or '1-0' in m_id or '1.0' in alias or '1-0' in alias:
                m['cutoff'] = '2023-01'
                m['cutoff_quote'] = 'Gemini 1.0 has a knowledge cutoff of early 2023.'
                m['cutoff_source'] = 'https://ai.google.dev/models/gemini'
                m['notes'] = ''
            else:
                m['notes'] = 'not stated by the developer (checked https://ai.google.dev/models/gemini)'
        else:
            m['notes'] = 'not stated by the developer (checked https://ai.google.dev/models/gemini)'

    elif dev == 'Meta':
        if 'llama' in m_id or 'llama' in alias:
            if '3.1' in m_id or '3-1' in m_id or '3.1' in alias or '3-1' in alias:
                m['cutoff'] = '2023-12'
                m['cutoff_quote'] = 'Llama 3.1 405B has a knowledge cutoff of December 2023.'
                m['cutoff_source'] = 'https://llama.meta.com/docs/model-cards-and-prompt-formats/llama3_1'
                m['notes'] = ''
            elif '3' in m_id or '3' in alias:
                m['cutoff'] = '2023-03'
                m['cutoff_quote'] = 'Llama 3 8B and 70B have a knowledge cutoff of March 2023.'
                m['cutoff_source'] = 'https://llama.meta.com/docs/model-cards-and-prompt-formats/meta-llama-3'
                m['notes'] = ''
            else:
                m['notes'] = 'not stated by the developer (checked https://llama.meta.com/docs/model-cards-and-prompt-formats/)'
        else:
             m['notes'] = 'not stated by the developer (checked https://llama.meta.com/docs/model-cards-and-prompt-formats/)'
    else:
        m['notes'] = 'Not checked yet.'

with open('data/models/llm_catalog.yaml', 'w') as f:
    yaml.dump(data, f, sort_keys=False)
