"""Offline tests for routing. Run:  python -m unittest discover -s tests -v"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from beacon import llm as llm_mod  # noqa: E402
from beacon.brain import Brain  # noqa: E402
from beacon.kb import KnowledgeBase  # noqa: E402


class FakeBonsai:
    """Returns whatever the test queued, and records what it was asked."""

    def __init__(self):
        self.replies = []
        self.seen = []
        self.calls = 0
        self.down = False

    def chat(self, messages, max_tokens=200, schema=None):
        if self.down:
            raise llm_mod.LLMError("down")
        self.seen.append(messages)
        self.calls += 1
        return self.replies.pop(0), {"ms": 5, "tokens": 9, "model": "fake"}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase()
        self.llm = FakeBonsai()
        self.brain = Brain(self.kb, self.llm)

    def say(self, text, reply=None):
        if reply is not None:
            self.llm.replies.append(reply if isinstance(reply, str) else json.dumps(reply))
        return self.brain.turn(text)

    def test_every_card_is_well_formed(self):
        for c in self.kb.cards:
            self.assertGreaterEqual(len(c["steps"]), 4, c["id"])
            self.assertIn(c["severity"], ("critical", "urgent", "minor"))
            for s in c["steps"]:
                self.assertLessEqual(len(s["text"].split()), 40, "too long to say aloud: " + s["text"])

    def test_keyword_search_finds_the_obvious_card(self):
        cases = {
            "my friend cut his leg and it won't stop bleeding": "severe_bleeding",
            "she spilled boiling water on her arm": "burn",
            "we lost the trail and there is no signal": "lost",
            "the whole building is shaking": "earthquake",
            "a rattlesnake bit my ankle": "snakebite",
            "he got stung by a bee and his throat is closing": "anaphylaxis",
            "the power went out in the storm": "power_outage",
            "he is shivering and soaked and slurring": "hypothermia",
        }
        for text, want in cases.items():
            hits = self.kb.search(text)
            self.assertTrue(hits, text)
            self.assertEqual(hits[0][0]["id"], want, text)

    def test_bonsai_opens_a_card_and_step_one_is_read_verbatim(self):
        out = self.say("there's blood everywhere, he fell on a rock",
                       {"card": "severe_bleeding", "say": "Okay, he's bleeding from the fall. I'll guide you.", "note": "Fell on rock, bleeding."})
        self.assertEqual(out["route"], "bonsai")
        self.assertEqual(out["card"]["id"], "severe_bleeding")
        self.assertEqual(out["say"][1], "Step one. " + self.kb.by_id["severe_bleeding"]["steps"][0]["text"])
        self.assertIn("Fell on rock, bleeding.", out["notes"])

    def test_next_repeat_back_never_call_the_model(self):
        self.say("bleeding badly", {"card": "severe_bleeding", "say": "Okay.", "note": ""})
        before = self.llm.calls
        self.assertEqual(self.say("Okay, next.")["step"], 1)
        self.assertEqual(self.say("Repeat that")["step"], 1)
        self.assertEqual(self.say("what's next?")["step"], 2)
        self.assertEqual(self.say("go back")["step"], 1)
        self.assertEqual(self.say("step four")["step"], 3)
        self.assertEqual(self.llm.calls, before)
        self.assertEqual(self.brain.session.turns["rule"], 5)

    def test_not_breathing_opens_cpr_without_the_model(self):
        out = self.say("Oh my god he's not breathing!")
        self.assertEqual(out["route"], "fastpath")
        self.assertEqual(out["card"]["id"], "cpr")
        self.assertEqual(self.llm.calls, 0)

    def test_breathing_but_unconscious_is_left_to_the_model(self):
        out = self.say("she passed out but she is still breathing",
                       {"card": "recovery_position", "say": "Okay, she's breathing. I'll guide you.", "note": ""})
        self.assertEqual(out["card"]["id"], "recovery_position")

    def test_question_keeps_the_card_and_sends_its_text_to_the_model(self):
        self.say("bad burn from the stove", {"card": "burn", "say": "Okay.", "note": ""})
        out = self.say("can I put ice on it?", {"card": "burn", "say": "No ice. Use cool running water.", "note": ""})
        self.assertEqual(out["intent"], "answer")
        self.assertEqual(out["say"], ["No ice. Use cool running water."])
        self.assertIn("No ice, butter, oil or toothpaste", self.llm.seen[-1][-1]["content"])

    def test_model_can_switch_cards_when_things_change(self):
        self.say("bad burn from the stove", {"card": "burn", "say": "Okay.", "note": ""})
        out = self.say("now she's fainted, she is breathing though", {"card": "recovery_position", "say": "Okay, switching.", "note": ""})
        self.assertEqual(out["card"]["id"], "recovery_position")
        self.assertEqual(out["step"], 0)

    def test_made_up_card_ids_and_rambling_are_contained(self):
        out = self.say("my tooth hurts", {"card": "dentistry", "say": "One. Two. Three. Four.", "note": ""})
        self.assertIsNone(out["card"])
        self.assertEqual(out["say"], ["One. Two."])

    def test_truncated_json_is_salvaged(self):
        out = self.say("we are lost", '{"card": "lost", "say": "Okay, you have lost the trail. Stay')
        self.assertEqual(out["card"]["id"], "lost")

    def test_think_block_is_ignored(self):
        self.assertEqual(llm_mod.extract_json('<think>hmm {"x":1}</think>{"card": "lost", "say": "ok", "note": ""}'.split("</think>")[1])["card"], "lost")

    def test_model_down_still_opens_the_best_card(self):
        self.llm.down = True
        out = self.say("my friend is bleeding a lot from a deep cut")
        self.assertEqual(out["route"], "retrieval")
        self.assertEqual(out["card"]["id"], "severe_bleeding")

    def test_handoff_falls_back_to_a_template(self):
        self.say("bleeding badly", {"card": "severe_bleeding", "say": "Okay.", "note": "Deep cut on leg."})
        self.llm.down = True
        report = self.brain.handoff()
        self.assertEqual(report["route"], "template")
        self.assertIn("Deep cut on leg.", report["report"])

    def test_start_over_clears_everything(self):
        self.say("bleeding badly", {"card": "severe_bleeding", "say": "Okay.", "note": ""})
        out = self.say("Start over.")
        self.assertIsNone(out["card"])
        self.assertEqual(len(out["log"]), 1)


if __name__ == "__main__":
    unittest.main()
