# Data sources for hypothesis verification and cost/time estimation

> Companion to [design notes](working-notes.md). Survey of knowledge bases, data repositories, literature sources and cost/duration sources, plus how to wire them into the pipeline.
> Status tags: **[V]** = checked via web search/fetch (summary level, not the official docs unless stated); **[L]** = live API/file call (2026-10-14 unless another date is given; see section 12); **[K]** = from general knowledge, not re-verified now. Access terms, limits and licenses change: re-check the official docs before building on any row. Last updated: 2026-10-19.

---

## 0. Two facts that shape everything

1. **Open Genes** [V] (announcement on lifespan.io; curated, open, with API and web UI; community MCP wrapper exists). Integrate it first.
2. **Backtests need data "as of date T".** Many curated DBs (DrugAge, OpenGenes, RAID) contain post-T entries. Every record must carry a publication/entry date, and the backtest must filter by it. Otherwise labels leak.

---

## 1. Literature and metadata

| Source | What it gives | Access (as understood) | Use in pipeline |
|---|---|---|---|
| PubMed / E-utilities **[K]** | abstracts, MeSH, links | free, NCBI API key raises limits | main biomedical retrieval |
| Europe PMC REST **[V]** | metadata, citations, references, links to databases, OA full text; no key required | free | retrieval + full-text spans for quotes |
| PMC Open Access subset **[K]** | full text of OA articles | free | quote extraction |
| PubTator 3.0 **[V]** | precomputed entities (6 types) and 12 relation types over ~36M abstracts and ~6M PMC OA full texts, weekly refresh; API for search, export (BioC), custom-text annotation | free API | gene/chemical/disease normalization; relation search; pairs with LLM to improve factuality (reported by the authors) |
| bioRxiv / medRxiv API **[K]** | preprints | free | recency, but mark as non-peer-reviewed |
| OpenAlex **[V]** | works, authors, citations graph | free tier: ~$0.10/day without key, ~$1/day with free key; singleton lookups free; one third-party source claims keys are mandatory since Feb 2026, official pages say otherwise — check live | citation graph, topic density, dates |
| Semantic Scholar API **[V]** | graph, citation contexts and intents (per third-party description) | rate limits reported inconsistently | citation context (supporting vs background) |
| Crossref **[K]** + Retraction Watch **[V]** | DOI metadata; retractions via `filter=update-type:retraction`; daily CSV dump (GitLab) | free | **retraction check on every cited source** |
| scite smart citations (supporting/contrasting) **[K]** | citation stance | commercial/API | not verified now; candidate for "contested" status |
| PubPeer **[K]** | post-publication comments | no stable API known | manual/flag only |
| Unpaywall, CORE, OpenCitations **[K]** | OA links, aggregated OA, open citations | free | full-text access |
| Cochrane Library, Epistemonikos **[K]** | systematic reviews | partly paywalled | highest evidence tier for human claims |
| alphaXiv **[V]** | arXiv only, no biomedical journals | connector | for methods papers, not biology |

## 2. Aging-specific knowledge bases

| Source | Content | Access | Use |
|---|---|---|---|
| **Open Genes** **[V]** | ~2,400 genes from ~1,700 papers, lifespan-altering interventions in model animals, longevity-associated variants, hallmark links; confidence grading by 6 study types and 12 criteria | API + web; community MCP over SQLite | gene-level evidence, hallmark mapping, confidence prior |
| HAGR: GenAge, AnAge, GenDR, LongevityMap, DrugAge, CellAge **[V]** | ageing genes (human >300, model organisms >2,000); animal life-history (>4,000 species); dietary-restriction genes; human longevity variants (LongevityMap: 550 entries in the live check); >1,000 compounds in model organisms (1,046 in the live check, section 12); senescence genes | downloads page; no API mentioned; terms on legal page | analogs and base rates (DrugAge), gene priors |
| **RAID** (Rodent Aging Interventions Database, LEV Foundation) **[V]** | published mouse/rat lifespan-extension studies (normal-lifespan strains, significant effect on mean or max lifespan) | project page with visualization; periodic updates | analogs, rodent lifespan base rates (note: inclusion criterion = significant effect, so positive-only) |
| **NIA ITP** results **[V partial]** | multi-site (3 sites) UM-HET3 mouse lifespan program, designed to detect 10% change in mean lifespan at 80% power with ≥2 sites; positives include rapamycin, acarbose, 17α-estradiol, NDGA | public portal after publication; JAX aging center lists ITP data and Mouse Phenome Database | `multi_site_program` flag; cleanest backtest labels (spec section 8; [design notes](working-notes.md) item A2) |
| Mouse Phenome Database **[V partial]** | curated mouse phenotype data incl. UM-HET3 | public | phenotype context |
| Aging Atlas, Tabula Muris Senis, single-cell aging atlases **[K]** | expression across age | public | data for falsification tests (Popper-style) |
| Biomarkers of Aging Consortium, epigenetic clock resources **[K]** | clock definitions and validation | various | biomarker-type hypotheses |
| Longevity Genie **[V earlier]** | open RAG/agents over longevity DBs (VitaDAO-funded) | open source | reference implementation |

## 3. Molecular, pathway, chemistry and target knowledge

| Source | Content | Access | Use |
|---|---|---|---|
| UniProt, HGNC, Ensembl, NCBI Gene **[K]** | identifiers, sequences | free | ID normalization |
| Gene Ontology, Reactome, KEGG **[K]** | functions, pathways | GO/Reactome open; KEGG has license limits | mechanism chain checks |
| STRING, BioGRID, IntAct **[K]** | interactions | free | neighborhood/mechanism plausibility |
| ChEMBL, PubChem **[K]** | compounds, bioactivity | free | intervention normalization, target engagement |
| DrugBank, DisGeNET **[K]** | drugs, gene-disease | license limits | check terms before use |
| **Open Targets Platform** **[V]** | target-disease evidence from many sources (GraphQL, BigQuery, bulk) | free; one third-party page says ~10 req/s | evidence for target–disease links; **association scores are not confidence values** (EBI note) |
| GWAS Catalog, GTEx, eQTL Catalogue **[K]** | genetic associations, expression | free | test implications on human genetic data (Popper used GTEx, GWAS Catalog, BioGRID) |
| Human Protein Atlas **[K]** | protein expression | free | tissue plausibility |
| Biomedical knowledge graphs (Hetionet, PrimeKG, SPOKE) **[K, not verified now]** | integrated graphs | varies | link/path discovery; quality depends on source DBs |

## 4. Experiment and omics repositories (raw evidence for falsification)

| Source | Content | Access | Use |
|---|---|---|---|
| GEO (NCBI) **[K]** | expression datasets | E-utilities `gds` | secondary analysis of public data |
| ArrayExpress → **BioStudies** **[V]** | migrated in 2021; REST API with keyword/species/experiment-type filters | free | dataset search |
| ENA/SRA, PRIDE, MetaboLights **[K]** | sequence, proteomics, metabolomics | free | deeper evidence |
| **IMPC** **[V]** | knockout mouse phenotypes (DR23.0, 2025: >100M data points, 9,277 genes), Solr API and FTP bulk | free (license: verify; one source says CC-BY 4.0) | gene function evidence; **weak for aging**: few mid/late-adult calls (~4.7k vs ~58k early adult) |
| Zenodo, Dryad, Figshare **[K]** | supplementary data | free | reproduce analyses |
| UK Biobank, NHANES **[K]** | human cohorts | controlled/open | human association tests (access conditions apply) |

## 5. Trials, regulatory and safety

| Source | Content | Access | Use |
|---|---|---|---|
| **ClinicalTrials.gov** (API v2, AACT relational copy) **[V partial]** | trial records, JSON; one source says public domain, no auth; AACT is a relational mirror | free | status, durations, enrollment, sponsor, results |
| WHO ICTRP, EU CTIS **[K]** | other registries | free | coverage outside US |
| DailyMed, openFDA/FAERS **[K]** | labels, adverse events | free | safety, approved indications |
| Trial outcome/duration research datasets (CT Open, TrialDura etc.) **[V as titles]** | prediction benchmarks | open | models for duration/success to compare against |

## 6. Cost and time sources (experiments, studies, trials)

| Source | What it gives | Caveat |
|---|---|---|
| **NIH RePORTER** (API, ExPORTER bulk) **[V]** | funded projects: title, abstract, PI, organization, total/direct/indirect cost fields (from third-party field list; check official Data Elements PDF V2); linked publications and patents | grant cost ≠ true cost; lag/sync caveats reported |
| NSF Awards, CORDIS (EU), Wellcome/UKRI grants **[K]** | funding amounts | coverage differs by funder |
| ClinicalTrials.gov start/completion dates, enrollment **[V partial]** | observed durations and size by phase/condition | planned vs actual dates; withdrawn/terminated handling |
| **Moore et al., JAMA Intern Med 2018** **[V]** | modeled median cost of pivotal trials $19.0M (IQR $12.2–33.1M; 138 trials, 59 approvals, 2015–2016); controlled trials mean $35.1M vs uncontrolled $13.5M; range <$5M to $346.8M | modeled with a CRO cost tool, not disclosed spending; drug approval trials, not aging-specific |
| NHGRI sequencing cost series **[V]** | modeled cost per genome/megabase through 2022 | modeled; not project actuals |
| protocols.io **[V]** | public protocols via REST (client token reads public data); step durations exist | duration is per step; no experiment-level duration found |
| NIA aged rodent colonies **[V partial]** | animal source for aging research; since 2014 NIA no longer charges users (older price ~$72 for a 2-year-old mouse; real cost estimate ~$1,400 for 32-month-old) | restricted eligibility; current policy must be checked with NIA |
| Vendor/core-facility price lists (JAX, university animal-care charges) **[K/V partial]** | per-diem and per-animal costs | institution-specific; compile your own table |
| ITP design parameters **[V]** | sample-size logic (10% effect, 80% power) | gives realistic cohort-size inputs |
| Reproducibility projects (cancer biology, psychology) **[K]** | replication rates and effect shrinkage | discipline-specific priors |

## 7. Patents

| Source | Notes |
|---|---|
| PatentsView API **[V]** | US patents/applications; ~45 queries/min; CPC filters (A61K, C12N, G16B); free key raises limits; BigQuery copy of history |
| Lens.org **[V]** | worldwide patents + scholarly works; PatSeq for sequences disclosed in patents; **access terms conflict between sources** (trial vs free non-commercial) |
| Google Patents Public Data (BigQuery) **[V]** | SQL across global patents; query cost in your own cloud project; one guide says repository archived — use current docs |
| EPO OPS, WIPO PATENTSCOPE **[K]** | other families |

## 8. Tool layers that already wrap many of these

- **BioMCP** **[V]**: MIT-licensed; 24 tools (think/search/fetch + domain tools) over PubMed, PubTator, ClinicalTrials.gov, MyVariant.info, OncoKB; Python version ended at 0.7.3, project rewritten in Rust; TypeScript fork claims federation over 50+ APIs (incl. Europe PMC, ClinVar, Open Targets).
- **Open Genes MCP** (community) **[V]**: read-only SQLite wrapper with four tables joined on HGNC symbols.
- **ToolUniverse** (Harvard, Zitnik lab) **[seen as a link only]**: includes an IMPC tool; not evaluated.
- **Other**: Biomni was not found in the search; do not assume.

---

## 9. Integration design

### 9.1 Layers

1. **Connector layer** (one thin, typed client per source): `search`, `fetch`, `normalize`. Caching with version/date stamps, retry/rate-limit handling, license metadata. Use BioMCP / existing MCPs for prototypes; own connectors for the core five (Europe PMC/PubMed, PubTator, Open Genes, ClinicalTrials.gov, Crossref/RW).
2. **Identifier normalization**: map every entity in the hypothesis card to HGNC/UniProt (genes/proteins), ChEMBL/PubChem (compounds), MeSH/MONDO (diseases), GO/Reactome (pathways), hallmark enum. PubTator is the first normalizer; unresolved entities stay `unresolved` and lower confidence.
3. **Evidence record** (uniform output of every connector):
   `{source, record_id, entity_ids[], claim_text, quote_span, publication_date, retrieved_at, version, study_type, species, tier, license}`.
   The verification layer works only on evidence records, never on free LLM statements.
4. **Source tiers** (superseded by the epistemic types of section 13 and the evidence profile: conflicts are shown, not resolved by tier; machine-derived relations never set a status): (1) curated with explicit criteria (Open Genes, ITP, trial registry results), (2) peer-reviewed text with extracted quotes, (3) text-mined relations (PubTator, Open Targets text-mining evidence), (4) preprints, (5) LLM inference (never counts as evidence, only as a lead).

### 9.2 Mapping to the hypothesis card (declared vs verified layer)

| Card field | Verified from |
|---|---|
| entities, mechanism | normalization + UniProt/GO/Reactome/STRING |
| hallmarks | Open Genes hallmark links; manual enum mapping fallback |
| analogs, base rates | DrugAge, RAID, Open Genes interventions, ITP |
| consensus / counterevidence | literature retrieval (Europe PMC/PubMed/S2) + PubTator relations + citation contexts + retraction filter |
| novelty (delta to closest prior) | card vs own KG (spec 8b); literature and patents as optional extra signals; coverage explicitly reported |
| evidence profile | epistemic types (section 13); `multi_site_program` labels from ITP/CITP, `robustness` from replication records |
| falsifiable implications | executable tests on GTEx / GWAS Catalog / GEO / Aging Atlas |
| cost, time of decisive experiment | trial registry durations; RePORTER costs; Moore et al. for human trials; animal/core-facility tables; protocols.io step durations |
| quality flags | retraction status, preprint status, source tier |

### 9.3 Cost/time estimation specifics

- Cost anchors and draft ordinal cost classes (ITP/CITP grant totals from NIH RePORTER, vivarium per diem rates, published trial cost estimates; checked 2026-10-19): [design notes](working-notes.md) section 3. Ranking uses the path to humans, the next step is shown separately (decided 2026-10-19).
- Build **reference classes** from ClinicalTrials.gov (by phase, condition, intervention type) for duration and enrollment, and from RePORTER (by activity code/topic) for academic study cost; use Moore et al. only as a sanity range for human pivotal trials.
- For rodent lifespan studies, build a table from protocol facts: cohort size from power calculation (ITP logic), duration from lifespan of strain (years), per-diem and animal costs from facility price lists (collect 2–3 institutional sources; the NIA subsidy is not a market price).
- Output distributions (median + interval), always with source list and what is modeled vs observed. Backtest: predicted vs actual durations of completed trials.

### 9.4 Temporal discipline (for backtests)

- Store `entry_date` for every row; DrugAge/RAID/Open Genes entries are filtered by the date of the underlying study.
- Use source snapshots (dump + retrieval date). For live APIs, record query time; for backtests, restrict by publication date, not retrieval date.
- LLM knowledge cutoff must precede T for the evaluated model, or leakage is possible (checked per HindSight design).

**Outcomes available after candidate T (counted 2026-10-19; PubMed, DrugAge Build 5 dump, ClinicalTrials.gov API v2).** Date = first public date (e-pub or preprint), not the journal issue date (an ITP paper in the Feb 2024 issue was online on 2023-12-02). Unit = one compound tested in one regimen; positives in brackets.

| Source | Quality | Species, endpoint | after 2022-12-31 | after 2023-12-31 | after 2024-12-31 | after 2025-06-30 |
|---|---|---|---|---|---|---|
| ITP | top: three sites, one protocol, negatives published | mouse, lifespan | 31 (7) | 24 (5) | 17 (3) | 17 (3) |
| CITP | top: three sites, panel of strains and species, negatives published | worm, lifespan | 27 (7) | 22 (5) | 22 (5) | 20 (5) |
| Randomized trials with posted results, candidate geroprotectors (metformin, acarbose, rapamycin, resveratrol, NR, SGLT2i, GLP-1 RA) | medium: mostly small | human, function and markers | 11 (n ≥ 100: 3) | 9 (3) | 6 (2) | 4 (2) |
| Single-lab studies (PubMed titles with "extends lifespan", rough) | low: almost only positives | worm, fly, mouse | ≈100–120 per year | | | |

- ITP batches: 2022-09-30 (8 tests, PMID 36179270), 2023-12-02 (7; astaxanthin and meclizine extend male lifespan, PMID 38041783), 2024-05-16 (7, PMID 38753230), 2025-09-19 (6; epicatechin, halofuginone, mitoglitazone in males, PMID 40973907), 2026-03-17 (11, none extended lifespan, PMID 41843349).
- CITP batches: 2023-11-04 (5, PMID 37923874), 2025-02-12 (2, PMID 40027526), 2025-07-21 preprint / 2025-12-23 eLife (16, 5 positive, PMID 41432067), 2026: levetiracetam, ATRA (FUdR-dependent), cinnarizine and meclizine (PMIDs 41993912, 42694712, 42807283).
- Failed repeats worth using as fixtures: in 2026 ITP found no benefit of astaxanthin, meclizine and mitoglitazone at other doses or later start (PMID 41843349); CITP found no effect of meclizine in worms (PMID 42807283).
- **DrugAge is not a source of post-T outcomes:** invertebrate entries end around 2021; Build 5 (2024-11-29) added mammals only; 7 papers from 2023–2024 in total. Use it for pre-T history and the KG; extract post-T outcomes from PubMed directly.
- Human trials give function and marker endpoints only: labels for `human_markers`-level claims, an endpoint mismatch for lifespan claims.
- Caveats: ITP results are sometimes presented at meetings before the paper, so the real public date can be earlier; the single-lab row is an order-of-magnitude title count; 2026 counts run to 2026-10-19.
- Implication: the cleanest test set is ≈ 40–60 compound tests, so only large differences between systems will be detectable; report wide intervals.

### 9.5 Risks

- Text-mined and score-based resources (Open Targets scores, PubTator relations) look like facts but are not confidence statements.
- Publication bias in DrugAge and RAID. Correction from live check: DrugAge does contain negative results (879 of 3,423 rows have a negative average-lifespan change), so it is not positive-only; RAID is, by inclusion criterion (significant effect only).
- License terms (DrugBank, KEGG, Lens, DisGeNET) and rate limits can block a public demo.
- Aging coverage gaps: IMPC mostly young animals; human aging outcomes are scarce.
- The Open Genes authors state that meeting one criterion does not prove a human longevity link: do not treat inclusion as validation.

## 10. Minimal viable set

Europe PMC + PubMed (retrieval), PubTator3 (normalization/relations), Crossref + Retraction Watch (quality), Open Genes + DrugAge + RAID + ITP (aging priors/analogs), ClinicalTrials.gov (duration/status), NIH RePORTER (cost), GTEx/GWAS Catalog/Open Targets (executable falsification tests), PatentsView (optional extra novelty signal). Everything else is an extension.

## 11. Not yet verified (to do)

Official docs for: Europe PMC limits, PubTator3 usage terms, Open Genes API schema and licence, HAGR terms and download formats, ClinicalTrials.gov v2 fields for dates, RePORTER cost fields; ITP data portal specifics; current NIA aged-colony policy; scite API; KG resources; Lens terms.

---

## 12. Live verification log (2026-10-14)

Direct HTTP calls. Results describe behaviour at that moment from one IP, not guarantees.

| Source | Result |
|---|---|
| **Open Genes API** [L] | Works without key. Swagger at `open-genes.com/api/docs`, OpenAPI at `open-genes.com/api/openapi.json` (title "Open Genes backend API", version 0.4.353; `/version` reports build 353, date 2023-05-03). `GET /api/gene/search` returned 2,405 genes (page size 20 by default, `pageSize` parameter works). Endpoints include `/gene/{id_or_symbol}`, `/gene/by-go-term/{term}`, `/gene/by-selection-criteria/{ids}`, `/gene/increase-lifespan`, `/research/lifespan-change` (2,497 records; fields include model organism, line, sex, diet, intervention result for lifespan, control/experiment cohort sizes, lifespan mean/median/max and change percent), `/research/age-related-changes`, `/research/gene-activity-change-impact`, `/research/associations-with-lifespan`, `/research/association-with-accelerated-aging`, `/research/other-evidence`, `/aging-mechanisms`, `/age-related-processes`, `/criteria`, `/disease`. Code: GitHub org `open-genes`, API repo `open-genes-api` (FastAPI, MPL-2.0); SQL dump downloadable from the project website; publication-search API and hackathon repos exist. License of the data itself: not confirmed. |
| **HAGR / DrugAge** [L] | `genomics.senescence.info/drugs/dataset.zip` downloads (CSV). **3,423 rows, 1,046 compounds, 664 PubMed IDs, 164 rows flagged ITP, 879 rows with negative average-lifespan change.** Top species by rows: C. elegans 1,586, D. melanogaster 981, M. musculus 372, S. cerevisiae 79, R. norvegicus 60. Columns: compound, species, strain, dosage, age at initiation, treatment duration, avg/max lifespan change % with significance, sex, weight change, `ITP`, `pubmed_id`. **No entry date column**: derive the date via PubMed ID for backtests. Other HAGR files confirmed on the download page (GenAge, AnAge, GenDR, LongevityMap, CellAge; SynergyAge not listed). Legal page: **CC BY 3.0**, free for all purposes including commercial, with attribution; for scientific papers cite de Magalhães et al. 2024 (HAGR update). No API; downloads come from the "latest stable build" without version stamps (older versions on request); the team asks to contact them rather than scrape. |
| **ClinicalTrials.gov API v2** [L] | `GET /api/v2/studies?query.term=...&fields=...` works without key; returns JSON with `protocolSection.statusModule.startDateStruct`, `completionDateStruct`, `designModule.enrollmentInfo` (count + type ACTUAL/ESTIMATED), paged by `nextPageToken`. Note completion dates may be estimated: use the enrollment `type` and status fields to separate planned from actual. |
| **Europe PMC REST** [L] | `search` works without key (`resultType=lite|core`, `cursorMark` paging, `pageSize`); core results carry `firstPublicationDate`, `isOpenAccess`, `license` (e.g., "cc by"). The **annotations API** (`/europepmc/annotations_api/annotationsByArticleIds`) returned text-mined spans with ontology URIs (e.g., ChEBI). The documentation page itself returned 403 to the fetch tool. Limits not read. |
| **PubTator3 API** [L] | `GET /research/pubtator3-api/search/?text=...` works without key and returns PMIDs, DOI, scores and highlighted entity tags (e.g., `@CHEMICAL_MESH:D020123`). The documentation page gave no content to the fetch tool; limits and licence not confirmed. |
| **NCBI E-utilities** [L] | `esearch` for PubMed works (1,473 hits for "rapamycin lifespan" at the time). Limits not extracted from the docs; NCBI documents key-based higher limits (general knowledge, not re-read). |
| **NIH RePORTER API v2** [L + docs] | `POST /v2/projects/search` works. Fields returned: `award_amount`, `direct_cost_amt`, `indirect_cost_amt`, start/end dates, activity code (example: R01 award 159,000 with direct 100,000 and indirect 59,000). **`total_cost` is not a field in the official page** (my earlier third-party-based note was wrong). Official guidance: ≤1 request/second, large jobs off-hours; `limit` max 500, project `offset` ≤ 14,999; publications linked by PMID/core project number; the page does not mention patents (my earlier claim about patents in RePORTER is not confirmed). |
| **Open Targets Platform** [L] | `POST /api/v4/graphql` works without key; reported API version 26.9.0, data version 2026.09. A GET with a query string returned HTTP 500 (use POST). |
| **ChEMBL** [L] | REST works (`/chembl/api/data/molecule/CHEMBL413.json`). |
| **UniProt** [L] | REST works (`rest.uniprot.org/uniprotkb/P42345.json`). |
| **Reactome** [L] | Content Service works; database version 97. |
| **STRING** [L] | API works; version 12.5. |
| **GTEx portal API v2** [L] | `/api/v2/dataset/tissueSiteDetail` works; my first gene-expression call was a 404 (wrong endpoint/parameters). |
| **GWAS Catalog** [L] | The legacy REST API returns **410 Gone**. The docs list new programmatic access: REST API (v2), **MCP server** for agents, and HuggingFace datasets. |
| **IMPC Solr** [L] | `genotype-phenotype` core responds without key (67,350 documents). |
| **Crossref + Retraction Watch** [L] | `filter=update-type:retraction` returns 76,226 results at the time. The full **Retraction Watch CSV** is downloadable from GitLab raw (about 67 MB, ~73k lines with fields including `OriginalPaperDOI`, `OriginalPaperPubMedID`, `RetractionNature`, `Reason`, `RetractionDate`). |
| **bioRxiv API** [L] | `/details/biorxiv/{from}/{to}/{cursor}` works without key. |
| **OpenCitations** [L] | `/index/api/v2/citation-count/doi:...` works without key. |
| **Unpaywall** [L] | Works only with a real contact email (422 otherwise). |
| **OpenAlex** [L] | **HTTP 429 without a key: "no API key, counts against the free daily budget shared by everyone on your network's IP address ... $0 remaining"**; the response says to use a free key (`api_key=` or Bearer). Practical conclusion: **get a free key**; keyless use is unreliable. |
| **Semantic Scholar** [L] | **HTTP 429** without a key (message suggests applying for a key). Practical conclusion: get a key. |
| **PatentsView** [L] | Request blocked (HTTP 502). Not verified. |
| **Lens.org API** [L] | HTTP 401 (token required). Terms not verified. |
| **protocols.io API** [L] | HTTP 400 without parameters/token (requires client token). |
| **AACT, ITP portal, Mouse Phenome Database, scite, DrugBank/KEGG/DisGeNET licences, Hetionet/PrimeKG/SPOKE** | Not verified (AACT needs an account; `phenome.jax.org/itp` returned 404; others not tested). Treat as open. |

Corrections made to earlier statements in this note: DrugAge is not positive-only; RePORTER has no `total_cost` field and its page does not mention patents; OpenAlex and Semantic Scholar keyless access is unreliable in practice.

---

## 13. Source anatomy: six epistemic types (2026-10-15)

What a source can *assert* matters more than its format. Every adapter maps its native unit to an evidence record with `epistemic_type`.

| Type | Examples (format, unit) | May set a claim status? |
|---|---|---|
| **A. Primary text** | PubMed (MEDLINE XML/text, article), Europe PMC (JSON metadata; JATS XML full text for OA), bioRxiv (JSON) | yes, only with verbatim quote and `quote_role: finding` |
| **B. Curated records** | DrugAge (CSV: compound × species × strain × dose × sex, `pubmed_id`), Open Genes (REST JSON: gene → `researches` blocks; lifespan records with cohort sizes, lifespan stats, significance; `doi`, sometimes empty `pmid`; gene `confidenceLevel`, `agingMechanisms`), GenAge human (CSV, 307 genes, field `why` incl. putative 53 / downstream 43), GenAge models (CSV, 2,205), LongevityMap (CSV, 550; 274 significant vs 274 non-significant), CellAge (TSV, 950; effect induces/inhibits/unclear; PMID), AnAge (TSV, 4,646 species; data quality, sample size) [L] | yes, together with a quote from the linked paper; inclusion alone is a signal, not proof |
| **C. Measurements** | GTEx (JSON API v2; 979 donors v8 with 10-year `ageBracket`, sex, Hardy scale), GEO (series matrix + processed files + SRA reads), BioStudies, IMPC (Solr JSON), ClinicalTrials.gov posted results [L] | yes, only via an executed test with recorded result |
| **D. Machine-derived** | PubTator3 (BioC JSON: passages, entity offsets, normalized IDs MeSH/NCBI Gene/taxon, document-level relations), Europe PMC annotations, Open Targets scores, HALD relations | **no**: leads for search only. Example: PubTator derived "Sirolimus – Negative_Correlation – Neoplasms" from Harrison 2009, whose abstract only speculates ("may … postponing death from cancer") |
| **E. Quality metadata** | Crossref `update-to`, Retraction Watch CSV, OpenCitations counts | no: flags on other records |
| **F. Plans and money** | ClinicalTrials.gov (dates with ACTUAL/ESTIMATED, enrollment), NIH RePORTER (`award_amount`, `direct_cost_amt`, `indirect_cost_amt`) | no: inputs to cost/time only |

Dates for backtests: PubMed and ClinicalTrials.gov have them; DrugAge/GenAge do not (derive via PMID); Open Genes `timestamp.changed` is the record edit date, not the study date.

## 14. Article metadata by source (checked on Harrison 2009, PMID 19587680) [L]

| Source | Fields observed | Use |
|---|---|---|
| PubMed XML | title, abstract, authors + affiliations, several dates (pub, article, history, revised), MeSH with qualifiers (NLM indexers), chemicals list (Sirolimus, mTOR protein mouse …), publication types (Journal Article; Research Support, N.I.H.), grants (11), IDs (PMID, PMCID, DOI, NIHMS), 30 references, comments/corrections links | publication type → epistemic role; MeSH/chemicals → normalization; grants → RePORTER cost link; corrections → quality |
| Europe PMC core JSON | + `citedByCount` (3,061), OA flag + licence, full-text URLs, `hasData`, `hasSuppl`, data links, db cross-references, text-mined flag | licence decides full-text use; data links bridge to raw data |
| Europe PMC full text | JATS XML for OA papers (an OA 2025 review: 11 sections, 74 references, 2 figures); **HTTP 500 for Harrison 2009** (author manuscript) | full text is not available for every paper |
| Crossref JSON | publisher, licence URLs (TDM), 30 references, `is-referenced-by-count` 3,387, relations; funder empty here | retractions/updates |
| OpenAlex JSON | topics, MeSH, institutions, **awards** (NIA AG 022308), counts by year, FWCI 66.4, referenced and related works, `is_retracted`, OA locations, abstract as inverted index; `study_designs` empty here; singleton lookups free, list queries use budget | citation graph for novelty/consensus; funders |
| Semantic Scholar JSON | citations 3,769, influential 106, TLDR, fields of study, OA PDF; citation contexts endpoint exists but returned empty contexts for two sampled citing papers | context/intent only when present |

Citation counts disagree (3,061 / 3,387 / 3,769) because coverage differs: fix one source per field.

## 15. Other article sources

- In use: PubMed, Europe PMC (incl. PMC OA and preprints), bioRxiv/medRxiv, Crossref, OpenAlex, Semantic Scholar, OpenCitations, Unpaywall.
- Add: **NIH RePORTER grant abstracts** (early signal of ongoing work, API checked), ClinicalTrials.gov posted results, **LibAge** (HAGR bibliographic library for ageing research; listed in the HAGR menu, page content not read).
- Not checked: CORE, OpenAIRE, BASE, Research Square, CyberLeninka (Russian OA).
- Paid, with institutional access: Scopus, Web of Science, **Embase** (best biomedical coverage; used by CT Open for validation), Dimensions, scite.

## 16. Raw data: contents and use

Contents (checked on GEO GSE345840, mouse, senescence): series matrix with per-sample characteristics (tissue, cell type, group, molecule, library strategy, processing description), processed supplementary files (e.g., featureCounts gene-level raw counts), raw reads in SRA. A GEO query "aging + Mus musculus + rapamycin" returned 55 series. GTEx v8: 979 donors with age brackets, sex, death circumstances; expression by tissue [L].

Procedure (Popper-style executable tests):
1. Turn a leaf of the claim graph into a **test spec before seeing data** (dataset criteria, variable, comparison, direction, statistic, threshold): protects against p-hacking.
2. Find datasets via metadata (organism, tissue, intervention, age annotation).
3. Check eligibility: required annotations present (age, control group). Usually the bottleneck.
4. Run standard methods in a sandbox (differential expression for counts; regression with covariates for GTEx), record code and versions.
5. Output an evidence record of type C (dataset, samples, test, effect, p/e-value, caveats).
6. Combine datasets via e-values or meta-analysis with multiple-testing control.

Examples: "gene X expression rises with age in human muscle" → GTEx regression on age bracket + sex + Hardy scale (caveats: brackets, cross-sectional, post-mortem). "Rapamycin lowers SASP genes in mouse tissue" → GEO rapamycin vs control, gene-set test (set e.g. from CellAge). Limit: tests mechanism links, never the human lifespan outcome.

## 17. Open knowledge graphs (checked 2026-10-15)

- **Wikidata** [L]: SPARQL works; rapamycin (Q32089) has ~40 linked statements (interacts with FKBP1A, conditions treated, drug interactions, producing taxa); references are sparse (2 of 5 "medical condition treated" statements referenced, both "Drug Indications Extracted from FAERS"); ~67,500 human gene items. Use for ID crosswalk and synonyms, not as evidence.
- **ORKG** [L]: API works; aging coverage near-empty ("longevity" 2 papers, "senescence" 1, "ageing" 9; "aging" 442 hits are mostly substring false positives such as "Packaging"). Not a source; its structured-contribution model is a design idea.
- **Monarch KG** [L]: API works (sirolimus → CHEBI:9168). **Open Targets** [L]. **INDRA** request timed out. Not checked: SemMedDB (subject–predicate–object with source sentence; UMLS licence), NCATS Translator (RTX-KG2, ROBOKOP), SPOKE, Hetionet, PrimeKG.
- Selection criterion: **edge provenance** (sentence or PMID). Without it an edge is type D.
- Roles: normalization/ID crosswalk; path candidates for mechanism chains; novelty by absent edges (with coverage caveat); direction-conflict checks.
- Aging-specific resources (HALD, AgingBank, AgeFactDB, SynergyAge, AGEID, Aging Atlas) and the own-KG design: see the knowledge-graph design.

## 18. Scope note

The survey above is mostly general biomedical sources plus an aging-specific layer. Checks were about format and availability; relevance for lifespan was checked only spot-wise (GTEx age brackets, GEO aging series, DrugAge rapamycin rows; IMPC weak for late ages; ORKG empty). A systematic per-source audit for aging/lifespan relevance is still to do.

## 19. late_start reference tables (collected 2026-10-21)

Inputs for the `late_start` indicator ([card spec](hypothesis-card-spec.md) 8a): fraction of median lifespan at the start of the intervention, capped at 1. Every number below comes from the cited source via API (PubMed / PMC / Europe PMC, WHO GHO, MeSH) or from the source's own supplementary data; nothing from memory.

**Lookup rule.** Look up species + strain + sex; if sex is unknown, take the `both` row if the table has one (a mixed population, e.g. humans), else the interval over sexes; if strain is unknown, the interval over all strains of the species in the table; species not in the table → `unknown` ([0, 1]). With an interval of medians [m_lo, m_hi], the fraction is [age / m_hi, min(1, age / m_lo)]. Months → days × 30.44.

### 19.1 Median lifespans of control groups

| Species | Strain / population | Sex | Median | Conditions | Source |
|---|---|---|---|---|---|
| mouse | UM-HET3 | female | 887 days (95% CI 879–898) | ITP controls pooled over 3 sites and 6 cohorts, 3,690 mice of both sexes | Cheng et al. 2019, *Aging Cell*, PMID 30801953 (text, section 2.1) |
| mouse | UM-HET3 | male | 803 days (95% CI 791–815) | as above | same |
| mouse | C57BL/6J | female | 866 days (95% CI 782–NA) | JAX lifespan study of 31 inbred strains, SPF; interim report, first cohort of 32 per sex | Yuan et al. 2009, *Aging Cell*, PMID 19627267 (Table 1) |
| mouse | C57BL/6J | male | 901 days (95% CI 859–NA) | as above | same |
| worm | *C. elegans* N2 | hermaphrodite | 19 days (range of trial medians 16–23) | CITP, 20 °C, 51 μM FUdR, assay plates set up on day 1 of adulthood; median of 28 trial-level Kaplan–Meier medians over 3 labs (2,877 worms); computed by us from Supplementary Data 3 | Lucanic et al. 2017, *Nat Commun*, PMID 28220799 |
| fly | *D. melanogaster* Dahomey | female (mated) | 63–70 days | 25 °C, SY food at 1.0 (100 g/L yeast; 69 Baker's, 70 Brewer's, 63 Torula); this is the peak over food concentrations, so a standard diet gives a shorter median | Bass et al. 2007, *J Gerontol A*, PMID 17921418 (text) |
| human | high-income countries (World Bank group) | both | 83.9 years | WHO life table 2023; age where l(x) = 50,000 of 100,000, linear interpolation between 5-year age groups; computed by us | WHO GHO API, indicator `LIFE_0000000031` (lx), `WB_HI`, 2023 |
| human | high-income countries | male | 81.1 years | as above | same |
| human | high-income countries | female | ≈ 85.7 years | the median falls in the open 85+ group (l(85) = 55,545); estimated with an exponential tail using e(85) = 6.63 years (`LIFE_0000000035`) | same |
| human | world | both / female / male | 79.5 / 82.1 / 76.6 years | WHO life table 2023, `GLOBAL`, same method | same |

Notes:
- Default for human hypotheses: high-income countries (where most aging trials run); the world row applies if the population names a low- or middle-income setting.
- Worms: ages are counted in days of adulthood (L4 = day 0). Conditions not stated in the card → the row applies (unstated = `n/a`, counts as a match, as everywhere in the card); a different temperature or no FUdR stated → `unknown`: the 20 °C value does not transfer (clarified 2026-10-21).
- Flies: the Dahomey female row at 25 °C; strain, sex or temperature not stated → the row applies; another strain, males or another temperature stated → `unknown`. Fly medians depend strongly on diet, so this row is weak.
- AnAge is not used: it lists maximum longevity only (checked 2026-10-21).
- Possible additions on demand: rat (e.g. ITP-style or NIA colony controls), more fly strains (Canton-S, w1118), worm at 25 °C.

### 19.2 Verbal ages → intervals

Mouse life phases follow The Jackson Laboratory, ["When are mice considered old?"](https://www.jax.org/news-and-insights/jax-blog/2017/november/when-are-mice-considered-old) (2017), which cites Flurkey, Currer & Harrison 2007, *The Mouse in Biomedical Research* (Elsevier). Human age groups follow the MeSH scope notes (NCBI E-utilities, db=mesh), the same groups PubMed uses for its age filters.

| Label (and synonyms) | Mouse, months | Mouse fraction, strain unknown | Human, years | Human fraction (median 83.9) |
|---|---|---|---|---|
| young adult, mature adult | 3–6 (JAX: "Mature adult mice range in age from 3 - 6 months") | 0.10–0.23 | 19–24 (MeSH Young Adult) | 0.23–0.29 |
| adult (unspecified) | 3–15 (our choice: mature adult to end of middle age) | 0.10–0.57 | 19–44 (MeSH Adult) | 0.23–0.52 |
| middle-aged | 10–15 (JAX: "at least 10 months old … upper age limit is about 14 - 15 months") | 0.34–0.57 | 45–64 (MeSH Middle Aged) | 0.54–0.76 |
| old, aged, late life, older adults, elderly | 18–24 (JAX: "18 - 24 months … meets the definition of 'old'") | 0.61–0.91 | ≥ 65 (MeSH Aged) | 0.77–1 |
| very old, oldest old | > 24 (JAX: "over 24 months of age can be considered 'very old'") | 0.81–1 | ≥ 80 (MeSH Aged, 80 and over) | 0.95–1 |

- The mouse fractions use the interval of all four mouse medians (803–901 days); with a known strain and sex the interval narrows (e.g. UM-HET3 females, "old": 0.62–0.82).
- JAX leaves gaps (6–10 and 15–18 months); a label that falls there ("late middle age") → the union of the neighbouring rows.
- Worms and flies: verbal labels → `unknown`; papers on these species state ages in days.
- A label not in the table → `unknown`; a frequent new label is added here with a source.
