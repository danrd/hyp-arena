# Task for Jules in the private repository longevity-kg: part B, null and negative results

(Text to paste into a Jules session whose source is danrd/longevity-kg. Only PMIDs below: no article text.)

---

Task for longevity-kg: add a second group of 50 articles (not in DrugAge) and extract their observations, with a focus on null and negative results.

1. Corpus. The 50 PMIDs below have no files in corpus/ yet. Fetch the title and abstract of each from PubMed (NCBI E-utilities, efetch, db=pubmed, retmode=xml) and write corpus/<pmid>.md in exactly the format of the existing files (front matter with pmid, doi, journal, year, publication_types, text_sha256, source; then "## Title" and "## Abstract"). The text_sha256 value must be computed the same way as in the existing files: look at how one existing file's hash relates to its text (and at the repository's history and notes) and reproduce it; if you cannot reproduce it exactly, write in notes.md the exact normalization you used. If a PMID has no abstract, write the file with the empty abstract and mark the PMID [!] in the queue.
2. Queue. Append the PMIDs to the end of queue.md under the heading "## Part B (null and negative results, not in DrugAge)", one line each in the existing format, status [ ]. Do not reorder existing lines.
3. Extraction. Process this group first, before the remaining part-A lines, following AGENTS.md exactly (one observation per intervention, organism group, dose and outcome; null and negative findings written with the same care as positive ones; quote_role finding, background or speculation; direction no_effect with significance NS where the article reports no significant change). Run validate.py on every file until it reports 0 with errors.
4. Pull request: add only corpus/ files, extracted/ files, queue.md and notes.md. List the PMIDs done and the [!] ones.

Do not use the files in gold/ for anything, as before. These 50 articles are a frozen test set: do not change AGENTS.md, validate.py or the extraction rules while processing them, and do not edit rows after they are written except to fix validation errors.

PMIDs: 39970115 35525932 33482307 29988130 39674829 31990212 39816859 37923362 40905413 35409746 42013845 41033584 39135281 36328784 31505678 41090071 37375717 25940747 40226291 25046958 41480958 35799302 42320027 22849329 40489973 31177635 17086191 38877845 41219805 31973570 30551452 27749245 29490275 39280279 21135231 34532960 39170193 41432067 36210437 39318968 30351306 26430545 28341216 37316917 35780219 41501832 39353373 39428437 29903004 33789838

PR title: "Part B: 50 articles with null and negative results, extracted"
