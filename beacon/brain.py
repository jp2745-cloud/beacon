"""Turn handling: decide what Beacon does with one thing the person said.

Three routes, cheapest first:

  rule      "next", "repeat", "go back", "stop" ... handled by a few regular
            expressions. No model call at all.
  fastpath  unmistakable life-threat phrases ("he's not breathing") open the
            CPR card immediately. Seconds matter more than nuance here.
  bonsai    everything else: Bonsai reads the messy sentence, picks the safety
            card, says one calm line, and extracts facts for the incident log.

The model never writes first-aid steps. Steps come word for word from
kb/protocols.json; Bonsai only routes, reassures and answers questions from
the open card's text.
"""
import re
import threading
import time

from . import llm as llm_mod

NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

_PUNCT = re.compile(r"[^a-z0-9' ]+")

_RULES = [
    ("reset", re.compile(r"^(please )?(start over|start again|reset|new emergency|clear( this| the)?( incident| log)?|we('re| are) (ok|okay|safe|fine) now)$")),
    ("stop", re.compile(r"^(please )?(stop|quiet|be quiet|pause|silence|stop talking|shut up|hush)$")),
    ("repeat", re.compile(r"^(please |can you |could you )?(repeat|again|say (that|it) again|repeat (that|it|the step|that step)|one more time|come again|what was that|what did you say|pardon|sorry what)( please)?$")),
    ("back", re.compile(r"^(please )?(go )?(back|previous)( a| one)?( step)?$|^(the )?(previous|last) step$")),
    ("timer", re.compile(r"^(please )?(start|set|begin)( the| a)? timer$")),
    ("next", re.compile(
        r"^(ok(ay)?|alright|all right|yes|yeah|yep|yup|got it|done|ready|sure)?[ ]?"
        r"(next|next step|next one|continue|go on|go ahead|keep going|what'?s next|what is next|what next|then what|and then|"
        r"now what|what now|what do i do next|i('ve| have)? (did|done) (that|it)|did (that|it)|that'?s done)?$")),
]
_STEP_JUMP = re.compile(r"^(go to |read |repeat )?step (number )?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)$")

_CPR_FAST = re.compile(
    r"\b(not|isn'?t|is not|aren'?t|stopped|no longer|not really) breathing\b|\bno pulse\b|\bcardiac arrest\b|"
    r"\b(start|do|need|give|doing|perform) cpr\b|\bhow (do i|to|do you) (do|give|perform|start) cpr\b"
)

SYSTEM_PROMPT = """You are Beacon, an emergency companion that runs entirely on this laptop with no internet. The person talking to you is stressed and may have their hands full. You never write first-aid steps yourself: vetted safety cards hold the steps, and the app reads them aloud. Your job is to understand what is happening, pick the right card, and say one short, calm thing.

Safety cards:
{index}

Reply with one JSON object and nothing else:
{{"card": "<card id from the list, or none>", "say": "<what you say out loud>", "note": "<facts for the incident log>"}}

Rules:
- "card" is the id of the card that fits best. Use "none" only when no card fits.
- "say" is at most two short sentences of plain spoken English. No lists, no emoji, no markdown.
- When you open a card, acknowledge what happened in the person's own terms and tell them you will guide them. Do not list steps, because the app reads step one right after you speak.
- When a card is already open and the person asks a question, keep that card and answer using only the open card's text. If the card does not cover it, say so and tell them to keep following the steps. Never invent doses, medicines or diagnoses.
- If the situation has changed into a different emergency, switch to that card.
- If no card fits, ask one short question to find out what is happening.
- "note" is under 15 words, facts only: who is hurt, what happened, where on the body. Use an empty string if there is nothing new.

Example 1
Open card: none
The person says: "my friend slipped on the rocks and there's a huge gash on his shin, it's bleeding a lot"
{{"card": "severe_bleeding", "say": "Okay, a deep cut on his shin. Stay with me, I'll walk you through stopping the bleeding.", "note": "Friend slipped on rocks. Deep cut on shin, heavy bleeding."}}

Example 2
Open card: severe_bleeding, on step 2 of 5
The person says: "should I take the shirt off to check if it stopped?"
{{"card": "severe_bleeding", "say": "No, keep the shirt pressed on. If blood soaks through, add more cloth on top.", "note": ""}}"""

HANDOFF_PROMPT = """You write handoff reports for emergency responders. Use only facts from the incident log below. Do not give advice and do not guess. Plain text, no markdown, exactly four short labelled lines:

Situation: who is affected and what happened.
Timeline: key moments with their clock times.
Actions taken: what the helper has done so far.
Unknown: important things the log does not say.

Incident log:
{log}"""


def _norm(text):
    t = text.lower().replace("’", "'")
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _step_line(card, idx):
    label = NUMBER_WORDS[idx] if idx < len(NUMBER_WORDS) else str(idx + 1)
    return "Step %s. %s" % (label, card["steps"][idx]["text"])


class Session:
    def __init__(self):
        self.reset()

    def reset(self):
        self.card_id = None
        self.step = 0
        self.log = []
        self.notes = []
        self.turns = {"rule": 0, "fastpath": 0, "bonsai": 0, "retrieval": 0}
        self.started = time.time()

    def add(self, who, text, kind="speech"):
        self.log.append({"ts": time.time(), "time": time.strftime("%H:%M:%S"), "who": who, "text": text, "kind": kind})


class Brain:
    def __init__(self, kb, bonsai):
        self.kb = kb
        self.bonsai = bonsai
        self.session = Session()
        self.lock = threading.Lock()
        index = "\n".join("- %s: %s. %s" % (c["id"], c["title"], c["summary"]) for c in kb.cards)
        self.system_prompt = SYSTEM_PROMPT.format(index=index)
        self.schema = {
            "type": "object",
            "properties": {
                "card": {"type": "string", "enum": [c["id"] for c in kb.cards] + ["none"]},
                "say": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["card", "say", "note"],
            "additionalProperties": False,
        }

    # -- public ------------------------------------------------------------
    def state(self):
        s = self.session
        return {
            "card": self.kb.public_card(s.card_id) if s.card_id else None,
            "step": s.step,
            "log": s.log[-200:],
            "notes": s.notes,
            "turns": s.turns,
        }

    def warmup(self):
        """Run the fixed part of the prompt through the model once. llama-server
        keeps it in its prompt cache, so real requests only process the new sentence."""
        try:
            self.bonsai.chat(
                [{"role": "system", "content": self.system_prompt},
                 {"role": "user", "content": 'Open card: none\nThe person says: "hello"'}],
                max_tokens=1,
            )
            self.bonsai.calls -= 1  # do not count the warm-up in the on-screen tally
            return True
        except llm_mod.LLMError:
            return False

    def reset(self):
        with self.lock:
            self.session.reset()
            return self.state()

    def open(self, cid):
        """Used when the person picks a card from the library on screen."""
        with self.lock:
            s = self.session
            if cid not in self.kb.by_id:
                return self._reply("rule", "none", [])
            s.turns["rule"] += 1
            out = self._open(cid, "", "rule")
            for line in out["say"]:
                s.add("beacon", line, "step")
            out["log"] = s.log[-200:]
            return out

    def set_step(self, idx):
        """Used when the person taps a step on screen."""
        with self.lock:
            s = self.session
            if not s.card_id:
                return self._reply("rule", "none", [])
            card = self.kb.by_id[s.card_id]
            s.step = max(0, min(int(idx), len(card["steps"]) - 1))
            line = _step_line(card, s.step)
            s.add("beacon", line, "step")
            s.turns["rule"] += 1
            return self._reply("rule", "step", [line])

    def turn(self, text):
        text = (text or "").strip()
        with self.lock:
            s = self.session
            if not text:
                return self._reply("rule", "empty", [])
            s.add("you", text)
            norm = _norm(text)

            out = self._rules(norm)
            if out is None:
                out = self._fastpath(norm)
            if out is None:
                out = self._bonsai(text)
            for line in out["say"]:
                s.add("beacon", line, "step" if line.startswith("Step ") else "speech")
            out["log"] = s.log[-200:]
            return out

    def handoff(self):
        with self.lock:
            s = self.session
            if not s.log:
                return {"report": "Nothing has happened yet, so there is nothing to hand off.", "route": "template", "llm": None}
            lines = []
            for e in s.log:
                who = {"you": "Helper said", "beacon": "Beacon said", "system": "Event"}.get(e["who"], e["who"])
                lines.append("[%s] %s: %s" % (e["time"], who, e["text"]))
            if s.notes:
                lines.append("Facts noted: " + " ".join(s.notes))
            log_text = "\n".join(lines[-60:])
            try:
                text, info = self.bonsai.chat(
                    [{"role": "user", "content": HANDOFF_PROMPT.format(log=log_text)}], max_tokens=280
                )
                text = text.replace("**", "").strip()
                if len(text) > 40:
                    s.turns["bonsai"] += 1
                    return {"report": text, "route": "bonsai", "llm": info}
            except llm_mod.LLMError:
                pass
            return {"report": self._template_report(), "route": "template", "llm": None}

    # -- routes ------------------------------------------------------------
    def _rules(self, norm):
        s = self.session
        if len(norm.split()) > 8:
            return None
        intent = None
        for name, rx in _RULES:
            if norm and rx.match(norm):
                intent = name
                break
        jump = _STEP_JUMP.match(norm)
        if intent is None and not jump:
            return None

        if intent == "reset":
            s.reset()
            line = "Cleared. Tell me what's happening."
            return self._reply("rule", "reset", [line])
        if not s.card_id:
            if intent == "stop":
                s.turns["rule"] += 1
                return self._reply("rule", "stop", [], stop=True)
            return None  # "next" with no card open means nothing; let Bonsai ask what is going on

        card = self.kb.by_id[s.card_id]
        last = len(card["steps"]) - 1
        s.turns["rule"] += 1
        if jump:
            raw = jump.group(3)
            n = int(raw) if raw.isdigit() else NUMBER_WORDS.index(raw) + 1
            if 1 <= n <= last + 1:
                s.step = n - 1
                return self._reply("rule", "step", [_step_line(card, s.step)])
            return self._reply("rule", "step", ["This card has %d steps." % (last + 1)])
        if intent == "next":
            if s.step < last:
                s.step += 1
                return self._reply("rule", "next", [_step_line(card, s.step)])
            return self._reply("rule", "next", ["That was the last step. Keep going until help arrives, and ask me anything."])
        if intent == "back":
            s.step = max(0, s.step - 1)
            return self._reply("rule", "back", [_step_line(card, s.step)])
        if intent == "repeat":
            return self._reply("rule", "repeat", [_step_line(card, s.step)])
        if intent == "timer":
            if card["steps"][s.step].get("timer"):
                return self._reply("rule", "timer", ["Timer started."], timer=True)
            return self._reply("rule", "timer", ["This step has no timer."])
        if intent == "stop":
            return self._reply("rule", "stop", [], stop=True)
        return None

    def _fastpath(self, norm):
        s = self.session
        if s.card_id == "cpr" or not _CPR_FAST.search(norm):
            return None
        s.turns["fastpath"] += 1
        return self._open("cpr", "Starting CPR guidance now.", "fastpath")

    def _bonsai(self, text):
        s = self.session
        hits = self.kb.search(text, k=3)
        active = self.kb.by_id.get(s.card_id) if s.card_id else None

        parts = []
        if active:
            parts.append("Open card: %s, on step %d of %d" % (active["id"], s.step + 1, len(active["steps"])))
            parts.append(self._card_text(active))
        else:
            parts.append("Open card: none")
        if hits:
            parts.append("Likely cards by keyword: " + ", ".join(c["id"] for c, _ in hits))
        if s.notes:
            parts.append("Known so far: " + " ".join(s.notes[-4:]))
        parts.append('The person says: "%s"' % text.replace('"', "'"))
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n".join(parts)},
        ]

        info = None
        obj = None
        try:
            raw, info = self.bonsai.chat(messages, max_tokens=160, schema=self.schema)
            obj = llm_mod.extract_json(raw) or llm_mod.salvage_reply(raw)
            if obj is None and raw and not raw.lstrip().startswith("{"):
                obj = {"card": active["id"] if active else "none", "say": raw, "note": ""}
        except llm_mod.LLMError:
            obj = None

        if obj is None:
            return self._retrieval_only(hits, active)

        s.turns["bonsai"] += 1
        cid = str(obj.get("card", "none")).strip()
        say = _clean_say(obj.get("say", ""))
        note = str(obj.get("note", "") or "").strip()
        if note and note.lower() not in ("none", "n/a", "empty") and note not in s.notes:
            s.notes.append(note[:160])

        if cid not in self.kb.by_id:
            cid = active["id"] if active else "none"
        if cid == "none":
            line = say or "Tell me what's happening, in a few words."
            return self._reply("bonsai", "ask", [line], llm=info)
        if active and cid == active["id"]:
            line = say or "Keep following the steps. Say next when you are ready."
            return self._reply("bonsai", "answer", [line], llm=info)
        return self._open(cid, say, "bonsai", llm=info)

    def _retrieval_only(self, hits, active):
        """Bonsai is unreachable. Still useful: open the best keyword match."""
        s = self.session
        s.turns["retrieval"] += 1
        if hits and hits[0][1] >= 2.0 and (not active or hits[0][0]["id"] != active["id"]):
            card = hits[0][0]
            return self._open(card["id"], "Opening the card for %s." % card["title"].lower(), "retrieval")
        if active:
            return self._reply("retrieval", "answer", ["I can't reach the language model right now. Keep following the steps, and say next when you are ready."])
        return self._reply("retrieval", "ask", ["I can't reach the language model, and no card matched. Try naming the emergency, like bleeding, burn, or lost."])

    # -- helpers -----------------------------------------------------------
    def _open(self, cid, say, route, llm=None):
        s = self.session
        card = self.kb.by_id[cid]
        s.card_id, s.step = cid, 0
        s.add("system", "Opened card: %s" % card["title"], "event")
        lines = [say] if say else []
        lines.append(_step_line(card, 0))
        return self._reply(route, "open", lines, llm=llm)

    def _reply(self, route, intent, say, llm=None, stop=False, timer=False):
        out = self.state()
        out.update({"route": route, "intent": intent, "say": [x for x in say if x], "llm": llm, "stop": stop, "timer": timer})
        return out

    @staticmethod
    def _card_text(card):
        lines = ["%s: %s" % (card["title"], card["summary"])]
        for i, st in enumerate(card["steps"]):
            lines.append("  %d. %s" % (i + 1, st["text"]))
        if card["dont"]:
            lines.append("  Do not: " + " ".join(card["dont"]))
        if card["redflags"]:
            lines.append("  Get help urgently if: " + "; ".join(card["redflags"]) + ".")
        if card["notes"]:
            lines.append("  Notes: " + " ".join(card["notes"]))
        lines.append("  " + card["call"])
        return "\n".join(lines)

    def _template_report(self):
        s = self.session
        card = self.kb.by_id.get(s.card_id) if s.card_id else None
        first = next((e for e in s.log if e["who"] == "you"), None)
        situation = " ".join(s.notes) if s.notes else (first["text"] if first else "Not recorded.")
        events = [e for e in s.log if e["kind"] in ("event", "step")]
        timeline = "; ".join("%s %s" % (e["time"], e["text"].split(". ", 1)[0] if e["kind"] == "step" else e["text"]) for e in events[-8:]) or "Not recorded."
        if card:
            done = "Following the %s card, reached step %d of %d." % (card["title"].lower(), s.step + 1, len(card["steps"]))
        else:
            done = "No card opened."
        return "Situation: %s\nTimeline: %s\nActions taken: %s\nUnknown: age, medical history, allergies and medicines were not recorded." % (situation, timeline, done)


def _clean_say(text):
    text = str(text or "").replace("\n", " ").replace("*", "").strip().strip('"').strip()
    text = re.sub(r"\s+", " ", text)
    # Hold the model to "two short sentences" even if it rambles.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2])
    return text[:260]
