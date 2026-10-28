# Annotation of abstracts for the extraction check

Input: `to_annotate.json` (50 abstracts, each `pmid`, `title`, `year`, `abstract`). Output: `annotated_b.json`, a JSON object
`{"annotator": "jules-draft", "papers": [...]}` with one entry per input paper, in the same order:

```json
{"pmid": "123", "records": [ {...}, ... ], "no_relevant_finding": false, "ambiguous": false, "note": ""}
```

A **record** is one result of the study reported in the abstract about the effect of one intervention on one endpoint in one species
(split by sex when the abstract reports the sexes separately). Fields:

| field | values |
|---|---|
| `quote` | a contiguous span copied **verbatim** from the abstract (title not allowed); one or two sentences at most |
| `quote_role` | `finding` (a result of this study), `background` (earlier work or context), `speculation` (a hypothesis or an expectation) |
| `intervention` | the compound or manipulation as named in the abstract |
| `endpoint` | `lifespan`, `healthspan`, `biomarker`, `disease`, `mechanism`, `unknown` |
| `effect` | direction of the intervention's effect on that endpoint as the quote states it: `increase`, `decrease`, `no_effect`, `unknown` |
| `significance` | `significant`, `not_significant`, `not_stated` |
| `species` | `mouse`, `rat`, `worm`, `fly`, `yeast`, `human`, `other` |
| `strain` | the strain if the abstract names it, else `""` |
| `sex` | `male`, `female`, `both`, `unspecified` |
| `dose` | the dose or regimen as written, else `""` |
| `system` | `in_vivo`, `ex_vivo`, `in_vitro` |
| `ambiguous` | true if two careful readers could label this record differently; then say why in `note` |

Rules.
1. Include null and negative findings (`effect: no_effect` or `decrease`) with the same care as positive ones; they are the point of this set.
2. Do not record background statements as findings. A sentence about earlier studies is `background`.
3. Do not infer what the abstract does not say: unknown strain is `""`, unknown sex is `unspecified`, an effect with no stated direction is `unknown`.
4. If the abstract has no result about an intervention's effect on lifespan, healthspan, a biomarker, a disease or a mechanism, set `no_relevant_finding: true` and `records: []`.
5. Label every record you would include; do not skip a record because it is hard. If you doubt a label, set `ambiguous` and explain in one sentence.
6. One record per intervention, species and sex group. Two compounds in one sentence are two records with the same quote.
7. Do not use outside knowledge about the paper, only the abstract text.

Check your file with `python -m scripts.check_annotations data/validation/extraction/annotated_b.json` before opening the pull request.
