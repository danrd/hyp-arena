# Targeted full-text re-read of records whose abstract may overstate (plan, 2026-11-09)

Status: plan; Argon pack 11 sent as the gold; no paid call yet. Numbers of record: specs/sources-argon-2026-11-09.yaml,
specs/abstract-overstates-2026-11-09.yaml.

## Why

Pack 10: the full text changed the stance of 2 of 28 papers, both a positive abstract turning into a null (LISA: the null
primary outcome left out of the abstract; PMID 31121926: a subgroup result presented as the result). One of them gave our
link +0.97 where the full text refutes it. Re-reading every paper's full text is not worth it (7% of papers); re-reading the
ones that look like this is.

## Steps

1. **Gold (free, sent): Argon pack 11.** 48 open-access RCT papers our reader used as evidence FOR a claim: 28 flagged by a
   crude code rule (a subgroup cue in the quote, or the abstract names a primary outcome) and 20 not flagged, mixed and
   blind to the arm. For each: abstract vs full text, and "does the abstract overstate", with the kind and the full-text
   sentence. It gives the prevalence, the precision of the rule and what it misses.
2. **A sharper flag (cheap, paid).** One DeepSeek call per record "for" from an RCT on the outcome link (231 records in both
   pools): does the abstract give the between-group result of the primary outcome it names; is the positive result
   restricted to a subgroup, a secondary outcome, a within-group change or a per-protocol analysis? Scored against pack 11
   before it is used. About 231 x 1.2 k tokens: about 0.05 USD.
3. **Re-read the flagged ones in full text** where PMC allows (about half): reader v13 on the abstract plus the methods and
   results excerpt (hyparena/tools/pmc.excerpt, 5-8 k characters). About 40-60 records x 3 k tokens: about 0.03-0.05 USD.
   Where the full text is closed: the record keeps its weight but carries a flag "abstract may overstate" (a weight rule for
   it, e.g. x 1/2 as GRADE's risk of bias, is a separate decision on R2 / R3).
4. **Check:** the two known cases must be caught; agreement with pack 11 on "overstates"; link and trial agreement with
   pack 8; R2 / R3 under the 0.03 rule.

**Price of steps 2-3: about 0.1 USD** (DeepSeek, off-peak), named before the run; step 1 is free.
