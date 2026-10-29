"""L1.17, descriptive (after the result): does an extraction error change the status of the claim? Per paper, the status of
"compound extends the lifespan of species" from the gold cells and from the cells of a verifier family (simplified rule: with sex scope
"any" an increase in one sex suffices; strict: an increase together with a null or decrease is contested). Prints agreement per family."""
import json, sys, collections
sys.path.insert(0, '.')
from scripts import extraction_compare as e

def status(cells, scope_any):
    up = any(c['direction'] == 'increase' for c in cells)
    against = [c for c in cells if c['direction'] in ('decrease', 'no_effect')]
    if scope_any:          # "at least one sex": an effect in one sex suffices, a null elsewhere does not count against
        return 'supported' if up else 'refuted' if against else 'unverified'
    return 'contested' if up and against else 'supported' if up else 'refuted' if against else 'unverified'

def main() -> None:
    kg = e.DEFAULT_KG; gold = e.load_gold(kg)
    for fam in ('deepseek', 'deepseek_rep', 'zhipu', 'google'):
        data = json.load(open(f'runs/stage5/l1_17/{fam}.json'))
        for scope in (True, False):
            agree = 0; conf = collections.Counter(); n = 0
            for it in data:
                g = [c for c in e.gold_cells(gold[it['pmid']]) if e._same_compound(c['compound'], it['compound']) and c['species'] == it['species']]
                if not g:
                    continue
                p = e.record_cells(it['records'], it['compound'])
                sg, sp = status(g, scope), status(p, scope)
                n += 1; agree += sg == sp
                if sg != sp: conf[(sg, sp)] += 1
            print(f"{fam:13s} {'sex_scope any' if scope else 'strict':13s} same status {agree}/{n} = {agree/n:.2f}  mismatches (gold -> model): {dict(conf)}")
    # repeat noise on statuses: deepseek vs deepseek_rep
    a = json.load(open('runs/stage5/l1_17/deepseek.json')); b = json.load(open('runs/stage5/l1_17/deepseek_rep.json'))
    for scope in (True, False):
        same = sum(status(e.record_cells(x['records'], x['compound']), scope) == status(e.record_cells(y['records'], y['compound']), scope) for x, y in zip(a, b))
        print('deepseek vs its repeat', 'sex_scope any' if scope else 'strict', f'{same}/{len(a)} = {same/len(a):.2f}')


if __name__ == "__main__":
    main()
