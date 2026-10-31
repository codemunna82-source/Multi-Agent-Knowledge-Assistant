"""Entity extraction. Default = transparent regex/heuristic extractor (emails, URLs, phones, money, dates, percentages, IDs,
capitalised names/organisations - Latin script only). With an LLM: sampled chunks are sent for typed extraction (any language) and
every returned value is kept ONLY if it occurs verbatim in the source text, so the model cannot invent entities."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Optional

from ..core import ProviderError, Unit, format_loc
from ..rag.steps import parse_json
from ..security.injection import SYSTEM_GUARD, wrap_untrusted

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December"
ID_PAT = re.compile(r"(?<![\w-])(?=[A-Za-z0-9\-_/]*\d)(?=[A-Za-z0-9\-_/]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9\-_/]*-[A-Za-z0-9\-_/]*[A-Za-z0-9](?![\w-])")
PATTERNS: dict[str, re.Pattern] = {
    "EMAIL": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "URL": re.compile(r"https?://[^\s<>)\"']+"),
    "MONEY": re.compile(r"(?:[$€£₹]|USD|EUR|INR|GBP|Rs\.?)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|thousand|k|M|B)\b)?|\b\d[\d,]*(?:\.\d+)?\s?(?:dollars|euros|rupees|USD|EUR|INR|GBP)\b"),
    "DATE": re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b|\b(?:{MONTHS})\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}}\b|\b\d{{1,2}}(?:st|nd|rd|th)? (?:{MONTHS}),? \d{{4}}\b"),
    "PERCENT": re.compile(r"\b\d+(?:\.\d+)?\s?%"),
    "ID": ID_PAT,
    "PHONE": re.compile(r"(?<![\w.-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,5}[\s.-])\d{3,5}(?:[\s.-]?\d{3,5})?(?!\w)(?!\.\d)"),
}
_CAP = r"[A-Z][a-zÀ-ɏ]+"
NAME = re.compile(rf"\b{_CAP}(?:\s+(?:de|van|von|bin|al|del|la)\s+)?(?:\s+{_CAP}){{1,3}}\b|\b[A-Z]{{2,6}}\s+{_CAP}\b")
ORG_SUFFIX = re.compile(r"\b(?:Inc|Ltd|LLC|Corp|Corporation|GmbH|Pvt|PLC|Co|Company|Group|Bank|University|Institute|Foundation|Technologies|Systems)\b\.?$")
STOP_FIRST = {"The", "This", "That", "These", "Those", "In", "On", "At", "For", "From", "With", "And", "But", "Or", "If", "When", "While", "After", "Before", "As", "By", "An", "A", "It", "Its",
              "We", "Our", "You", "Your", "He", "She", "They", "Their", "There", "Here", "What", "Which", "Who", "Where", "Why", "How", "All", "Any", "Each", "Every", "Some", "No", "Not",
              "To", "Of", "See", "Please", "Note", "Table", "Figure", "Section", "Clause", "Article", "Page", "Chapter", "Appendix", "Contact", "Dear", "Mr", "Mrs", "Ms", "Dr", "Thanks"}
NOT_NAMES = set(MONTHS.split("|")) | {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
TYPES_FOR_GRAPH = ("NAME", "ORG", "EMAIL", "ID")


def norm(v: str) -> str:
    return " ".join(v.lower().split())


def entities_in(text: str, types: Optional[Iterable[str]] = None) -> list[tuple[str, str]]:
    """-> [(TYPE, value)] in order of appearance (heuristic). Spans already claimed by a stricter type are not re-reported."""
    return [(t, v) for _, _, t, v in entity_spans(text, types)]


def entity_spans(text: str, types: Optional[Iterable[str]] = None) -> list[tuple[int, int, str, str]]:
    """-> [(start, end, TYPE, value)] in order of appearance."""
    want = set(types) if types else None
    taken: list[tuple[int, int]] = []
    out: list[tuple[int, int, str, str]] = []

    def free(a, b):
        return not any(a < y and x < b for x, y in taken)

    for typ, pat in PATTERNS.items():
        if want and typ not in want:
            continue
        for m in pat.finditer(text):
            v = m.group(0).strip(" .,;:")
            if typ == "PHONE" and len(re.sub(r"\D", "", v)) < 8:
                continue
            if typ == "ID" and (re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) or re.fullmatch(r"[\d-]+", v)):
                continue
            if free(m.start(), m.end()):
                taken.append((m.start(), m.end()))
                out.append((m.start(), m.end(), typ, v))
    if not want or want & {"NAME", "ORG"}:
        for m in NAME.finditer(text):
            words = m.group(0).split()
            while words and words[0] in STOP_FIRST:
                words = words[1:]
            if len(words) < 2 or any(w in NOT_NAMES for w in words):
                continue
            v = " ".join(words)
            typ = "ORG" if ORG_SUFFIX.search(v) else "NAME"
            if (not want or typ in want) and free(m.start(), m.end()):
                out.append((m.start(), m.end(), typ, v))
    out.sort()
    return out


def extract_source(units: list[Unit], llm=None, types: Optional[list[str]] = None, max_locations: int = 5) -> dict:
    """Aggregate over the COMPLETE source (heuristic) -> {TYPE: [{value, count, locations}]}; LLM adds typed entities from a sample."""
    agg: dict[str, dict[str, dict]] = defaultdict(dict)
    for u in units:
        for typ, v in entities_in(u.text, types):
            e = agg[typ].setdefault(norm(v), {"value": v, "count": 0, "locations": []})
            e["count"] += 1
            loc = format_loc(u.loc)
            if loc not in e["locations"] and len(e["locations"]) < max_locations:
                e["locations"].append(loc)
    method = "heuristic"
    if llm is not None and getattr(llm, "available", False) and units:
        step = max(1, len(units) // 12)
        sample = units[::step][:12]
        sys = (f'Extract named entities. JSON only: {{"entities": [{{"type": "PERSON|ORG|LOCATION|DATE|MONEY|PRODUCT|OTHER", "value": "<exact text>"}}]}}. '
               f"Copy each value exactly as written. {SYSTEM_GUARD}")
        added = 0
        for u in sample:
            try:
                j = parse_json(llm.complete(sys, wrap_untrusted(u.text[:3000], format_loc(u.loc))))
            except ProviderError:
                break
            for ent in (j or {}).get("entities", []) if isinstance(j, dict) else []:
                if not (isinstance(ent, dict) and isinstance(ent.get("value"), str) and isinstance(ent.get("type"), str)):
                    continue
                v, typ = ent["value"].strip(), ent["type"].upper()[:12]
                if not v or v.lower() not in u.text.lower() or (types and typ not in types):
                    continue  # reject anything that is not literally in the source: no hallucinated entities
                if norm(v) not in agg[typ]:
                    pat = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, v.split())) + r"(?!\w)", re.I)
                    cnt, locs = 0, []
                    for uu in units:
                        n = len(pat.findall(uu.text))
                        if n:
                            cnt += n
                            if len(locs) < max_locations:
                                locs.append(format_loc(uu.loc))
                    agg[typ][norm(v)] = {"value": v, "count": cnt, "locations": locs}
                    added += 1
        method = f"heuristic+llm({added} added)"
    out = {t: sorted(d.values(), key=lambda e: (-e["count"], e["value"])) for t, d in agg.items()}
    return {"method": method, "entities": out}


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])|\n+")


def chunk_entities(text: str) -> list[list[list[str]]]:
    """Entities per SENTENCE of a chunk (graph edges only link entities that co-occur in one sentence - far more precise than
    chunk-level co-occurrence). Computed at ingestion; cheap."""
    groups = []
    for sent in _SENT.split(text):
        seen, g = set(), []
        for typ, v in entities_in(sent, TYPES_FOR_GRAPH):
            k = (typ, norm(v))
            if k not in seen:
                seen.add(k)
                g.append([typ, v])
        if g:
            groups.append(g)
    return groups


# ----------------------------------------------------------------------------- typed relations (pattern based)
# (relation, regex over the text BETWEEN two neighbouring entities, passive?)  passive = the entity on the right is the subject
RELATION_PATTERNS: list[tuple[str, "re.Pattern[str]", bool]] = [
    ("reports_to", re.compile(r"^\s*(?:,\s*)?(?:who\s+|which\s+)?(?:directly\s+)?reports?\s+to\s*$", re.I), False),
    ("works_for", re.compile(r"^\s*(?:,\s*)?(?:who\s+)?(?:works?|worked|is\s+employed|are\s+employed|serves?|joined)\s+(?:at|for|with|by)\s*$|^\s*(?:,\s*)?(?:is|was)\s+an?\s+(?:employee|engineer|manager|director|consultant|analyst)\s+(?:at|of)\s*$", re.I), False),
    ("manages", re.compile(r"^\s*(?:,\s*)?(?:also\s+)?(?:manages|leads|heads|oversees|runs|directs|is\s+(?:the\s+)?(?:manager|head|lead|owner)\s+of)\s*$", re.I), False),
    ("approved", re.compile(r"^\s*(?:,\s*)?(?:also\s+)?(?:approved|authori[sz]ed|signed\s+off(?:\s+on)?|sanctioned)\s*$", re.I), False),
    ("approved", re.compile(r"^\s*(?:was|were|is|has\s+been)\s+(?:approved|authori[sz]ed|signed\s+off)\s+by\s*$", re.I), True),
    ("signed", re.compile(r"^\s*(?:,\s*)?(?:signed|countersigned)\s*$", re.I), False),
    ("signed", re.compile(r"^\s*(?:was|were|is)\s+(?:signed|countersigned)\s+by\s*$", re.I), True),
    ("acquired", re.compile(r"^\s*(?:,\s*)?(?:acquired|bought|purchased|took\s+over)\s*$", re.I), False),
    ("acquired", re.compile(r"^\s*(?:was|were|is)\s+(?:acquired|bought|purchased)\s+by\s*$", re.I), True),
    ("partner_of", re.compile(r"^\s*(?:,\s*)?(?:partners?\s+with|(?:has|have)\s+(?:a\s+)?(?:contract|agreement|partnership)\s+with|contracts?\s+with|is\s+a\s+(?:partner|supplier|vendor|client|customer)\s+of)\s*$", re.I), False),
    ("owns", re.compile(r"^\s*(?:,\s*)?(?:owns|owned|is\s+the\s+owner\s+of|holds\s+a\s+stake\s+in)\s*$", re.I), False),
    ("owns", re.compile(r"^\s*(?:is|was)\s+owned\s+by\s*$", re.I), True),
]
_MAX_GAP = 60


def chunk_relations(text: str) -> list[list]:
    """-> [[subject_type, subject, relation, object_type, object], ...] for neighbouring entity pairs in one sentence whose connecting words
    match a known pattern ('X reports to Y', 'Y was approved by X'). Deterministic and conservative: no pattern, no relation."""
    out, seen = [], set()
    for sent in _SENT.split(text):
        spans = entity_spans(sent, TYPES_FOR_GRAPH)
        for a, b in zip(spans, spans[1:]):
            gap = sent[a[1]:b[0]]
            if len(gap) > _MAX_GAP or re.search(r"[.!?;]", gap):
                continue
            for rel, pat, passive in RELATION_PATTERNS:
                if pat.match(gap):
                    subj, obj = (b, a) if passive else (a, b)
                    key = (subj[2], norm(subj[3]), rel, obj[2], norm(obj[3]))
                    if key not in seen:
                        seen.add(key)
                        out.append([subj[2], subj[3], rel, obj[2], obj[3]])
                    break
    return out
