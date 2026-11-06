"""Revision conflicts affect only the selected targets until the learner decides."""

import copy
import unittest

from progress_review import apply_progress_review, effective_record


class ProgressReviewTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "current": {"module": "02-list", "section": "02-reverse"},
            "questions_for_llm": ["原问题"],
            "pages": [
                {"module": "02-list", "section": "01-basics", "completed_at": "before"},
                {"module": "02-list", "section": "02-reverse", "completed_at": "before"},
                {"module": "03-tree", "section": "01-binary", "completed_at": "before"},
            ],
            "exercises": [
                {"module": "02-list", "section": "01-basics", "id": "keep-answer", "user_answer": "A"},
                {"module": "02-list", "section": "02-reverse", "id": "old-reverse", "user_answer": "B"},
            ],
            "completions": [{"module": "02-list", "section": "02-reverse", "exercise_ids": ["old-reverse"]}],
            "legacy_checkpoints": [],
        }
        self.review = {"items": [{
            "id": "R1", "reason": "重新组织反转步骤",
            "previous": [{"module": "02-list", "section": "02-reverse", "guided_status": "已掌握"}],
            "targets": [{"module": "02-list", "section": "02-reverse"}],
            "decision": None,
        }]}

    def test_unaffected_sections_and_saved_answers_are_preserved(self):
        original = copy.deepcopy(self.record)
        effective = effective_record(self.record, self.review)
        self.assertEqual(self.record, original)
        self.assertEqual(effective["pages"][0]["completed_at"], "before")
        self.assertNotIn("completed_at", effective["pages"][1])
        self.assertEqual(effective["pages"][2]["completed_at"], "before")
        self.assertEqual([x["id"] for x in effective["exercises"]], ["keep-answer"])
        self.assertEqual(effective["completions"], [])
        self.assertEqual(effective["questions_for_llm"], ["原问题"])

    def test_decided_targets_restore_progress_and_other_conflicts_remain(self):
        self.review["items"][0]["decision"] = "保留原进度"
        self.review["items"].append({
            "id": "R2", "targets": [{"module": "03-tree"}], "decision": None,
        })
        effective = effective_record(self.record, self.review)
        self.assertEqual(effective["pages"][1]["completed_at"], "before")
        self.assertNotIn("completed_at", effective["pages"][2])
        self.assertEqual(len(effective["exercises"]), 2)

    def test_deleted_target_does_not_reset_other_chapters(self):
        self.review["items"][0]["targets"] = []
        self.assertEqual(effective_record(self.record, self.review), self.record)
        state = {
            "meta": {"completed_modules": ["02-list", "03-tree"]},
            "domain_tree": {"nodes": {"02-list": {"status": "mastered"}, "03-tree": {"status": "mastered"}}},
            "learning_record": copy.deepcopy(self.record),
        }
        apply_progress_review(state, self.review)
        self.assertEqual(state["meta"]["completed_modules"], ["03-tree"])
        self.assertEqual(state["domain_tree"]["nodes"]["03-tree"]["status"], "mastered")

    def test_pending_parent_does_not_count_as_mastered(self):
        state = {
            "meta": {"completed_modules": ["02-list", "03-tree"]},
            "domain_tree": {"nodes": {
                "02-list": {"status": "mastered", "progress": 100},
                "03-tree": {"status": "mastered", "progress": 100},
            }},
            "learning_record": copy.deepcopy(self.record),
        }
        apply_progress_review(state, self.review)
        self.assertEqual(state["meta"]["completed_modules"], ["03-tree"])
        self.assertEqual(state["domain_tree"]["nodes"]["02-list"]["status"], "pending_confirmation")
        self.assertEqual(state["domain_tree"]["nodes"]["02-list"]["progress"], 100)
        self.assertEqual(state["domain_tree"]["nodes"]["03-tree"]["status"], "mastered")


if __name__ == "__main__":
    unittest.main()
