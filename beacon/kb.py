"""Safety cards and a tiny keyword retriever.

No embedding model on purpose: sixteen cards do not need one. Matching
phrases the way a person would say them is faster, costs no energy worth
measuring, and leaves the language model for the part that needs language.
"""
import json
import re

from . import config

_WORD = re.compile(r"[a-z0-9']+")
_STOP = set(
    "a an the and or but if then so to of in on at for with from by is are was were be been am i "
    "me my we our you your he she it they them his her its this that these those there here do does "
    "did have has had not no can could would should will just very really what how when where who "
    "help please need think know got get about up out off over into as".split()
)


def _stem(w):
    for suf in ("ing", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text):
    return [_stem(w) for w in _WORD.findall(text.lower().replace("’", "'")) if w not in _STOP]


class KnowledgeBase:
    def __init__(self, path=config.KB_PATH):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.about = data.get("about", "")
        self.cards = data["cards"]
        self.by_id = {c["id"]: c for c in self.cards}
        self._index = []
        for c in self.cards:
            phrases = []
            for kw in c["keywords"]:
                toks = tokens(kw)
                if toks:
                    phrases.append(toks)
            soft = set(tokens(c["title"] + " " + c["summary"]))
            self._index.append((c["id"], phrases, soft))

    def search(self, text, k=3):
        """Return [(card, score)] best first. Score 0 cards are dropped."""
        toks = tokens(text)
        tokset = set(toks)
        joined = " " + " ".join(toks) + " "
        scored = []
        for cid, phrases, soft in self._index:
            score = 0.0
            for ph in phrases:
                if len(ph) == 1:
                    if ph[0] in tokset:
                        score += 2.0
                elif " " + " ".join(ph) + " " in joined:
                    score += 2.0 + 1.5 * len(ph)
            score += 0.5 * len(tokset & soft)
            if score > 0:
                scored.append((self.by_id[cid], score))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def public_card(self, cid):
        c = self.by_id[cid]
        return {k: c[k] for k in ("id", "title", "category", "severity", "summary", "call", "steps", "dont", "redflags", "notes", "source")}
