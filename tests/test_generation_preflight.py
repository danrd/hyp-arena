from collections import Counter
import unittest

from scripts.argon.generation_preflight import evaluate, make_pairs


class GenerationPreflightTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "hypothesis_id": "H01",
            "novelty": "intervention_change",
            "known_result": "The original intervention changed the outcome.",
            "source_pmids": ["1"],
            "claim_level": "patient",
            "claim_span": "Patients",
            "scope": "target",
            "readiness": "verified",
            "reason": "The active comparator isolates the change.",
            "increment": "The modification adds benefit.",
            "contrast_span": "Compare modified and original A.",
            "refuting_result": "Equal outcomes despite target engagement.",
            "implementation_span": "Compare modified and original A.",
            "implementation_basis": "A is documented in the tested system.",
            "implementation_pmids": ["1"],
        }
        self.hypotheses = {"as_of": "2026-11-19", "hypotheses": [{
            "id": "H01", "claim": "Patients benefit from modified A.",
            "experiment": "Compare modified and original A.",
        }]}
        self.card = {"pico": {"population": {"taxon": "Homo sapiens"}},
                     "decisive_experiment": {"system": "human"}}
        self.dossier = {"cutoff_date": "2026-11-19",
                        "hypotheses": [{"hypothesis_id": "H01"}],
                        "sources": [{"source": {"pmid": "1"}}]}

    def evaluate(self):
        cases = [{"id": "H01", "card": self.card}]
        review = {"cutoff_date": "2026-11-19", "reviews": [self.row]}
        return evaluate(self.hypotheses, cases, self.dossier, review)["rows"]["H01"]

    def test_distinct_change_needs_author_comparison(self):
        self.assertTrue(self.evaluate()["frontier_eligible"])
        self.row["contrast_span"] = "A comparator added by the reviewer."
        with self.assertRaisesRegex(ValueError, "stated contrast"):
            self.evaluate()

    def test_transfer_remains_eligible_for_clinical_priority(self):
        self.row["novelty"] = "known_species"
        result = self.evaluate()
        self.assertEqual(result["novelty_ceiling"], "translation")
        self.assertFalse(result["frontier_eligible"])
        self.assertTrue(result["clinical_priority_eligible"])

    def test_mouse_prerequisite_cannot_enter_clinical_priority(self):
        self.card["decisive_experiment"]["system"] = "mouse"
        with self.assertRaisesRegex(ValueError, "cannot directly test"):
            self.evaluate()
        self.row.update(scope="prerequisite", tested_prerequisite="Target engagement",
                        remaining_gap="Effect in patients")
        result = self.evaluate()
        self.assertTrue(result["frontier_eligible"])
        self.assertFalse(result["clinical_priority_eligible"])

    def test_unknown_implementation_is_held(self):
        self.row["implementation_pmids"] = []
        with self.assertRaisesRegex(ValueError, "document an actual implementation"):
            self.evaluate()
        self.row["readiness"] = "unknown"
        result = self.evaluate()
        self.assertEqual(result["readiness"], 0)
        self.assertFalse(result["frontier_eligible"])
        self.assertFalse(result["clinical_priority_eligible"])

    def test_pairs_cover_the_selected_ids_with_balanced_positions(self):
        ids = [f"H{i:02d}" for i in range(1, 21)]
        pairs = [row["hypothesis_ids"] for row in make_pairs(ids)["pairs"]]
        self.assertEqual(len({frozenset(p) for p in pairs}), 190)
        left, right = [Counter(p[i] for p in pairs) for i in (0, 1)]
        self.assertTrue(all(sorted([left[h], right[h]]) == [9, 10] for h in ids))
