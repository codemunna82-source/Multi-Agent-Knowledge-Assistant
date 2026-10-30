"""Extended synthetic corpus + questions for the platform features added in v3: document versions, comparison, contradictions,
Hindi (exact search, retrieval, spreadsheet questions, summaries), analytics (trend / outliers) and parallel multi-agent answers.
Like sample.py, ground truth is computed from the generating data. It is a regression guard, NOT a benchmark of real-world accuracy."""
from __future__ import annotations

import re

from .dataset import EvalCase, EvalDataset, RelevantRef

POLICY_V1 = ("Leave policy.\n\nFull-time employees accrue 25 days of annual leave per calendar year. Unused days expire after 12 months.\n\n"
             "Remote work is allowed 3 days per week with manager approval.\n")
POLICY_V2 = ("Leave policy.\n\nFull-time employees accrue 30 days of annual leave per calendar year. Unused days expire after 12 months.\n\n"
             "Remote work is allowed 2 days per week with manager approval. A wellness stipend of 500 dollars is offered every year.\n")
HR_FAQ = ("Frequently asked HR questions.\n\nFull-time employees accrue 28 days of annual leave per calendar year.\n\n"
          "Questions about the handbook can be sent to Anjali Rao in the HR department.\n")
SUPPLIER_A = "Supplier A. Acme Supplies delivers steel bolts within 5 business days. Minimum order is 100 units.\n"
SUPPLIER_B = "Supplier B. Zenith Parts delivers copper wire within 9 business days. Minimum order is 40 units.\n"
HINDI = ("कर्मचारियों को साल में पच्चीस दिन की छुट्टी मिलती है। घर से काम करने की अनुमति सप्ताह में तीन दिन है।\n\n"
         "खर्च की रिपोर्ट तीस दिनों के भीतर जमा करनी होगी। सुश्री अंजलि राव मानव संसाधन विभाग की निदेशक हैं।\n")
BIKRI = [["कर्मचारी", "क्षेत्र", "बिक्री"], ["अमित", "उत्तर", 12000], ["बीना", "दक्षिण", 34000], ["चेतन", "उत्तर", 9000], ["दीपा", "पूर्व", 15500]]
ORDERS = [(f"{2023 + i // 12}-{i % 12 + 1:02d}-15", 9000 if i == 17 else 1000 + 10 * i) for i in range(24)]


def _csv(rows) -> bytes:
    return ("\n".join(",".join(str(c) for c in r) for r in rows) + "\n").encode()


def corpus() -> list[tuple[str, bytes]]:
    """Ordered (file name, content): the same name twice = version 1 then version 2."""
    return [("leave_policy.txt", POLICY_V1.encode()), ("leave_policy.txt", POLICY_V2.encode()), ("hr_faq.txt", HR_FAQ.encode()), ("supplier_a.txt", SUPPLIER_A.encode()),
            ("supplier_b.txt", SUPPLIER_B.encode()), ("hindi_policy.txt", HINDI.encode()), ("bikri.csv", _csv(BIKRI)), ("orders.csv", _csv([("Date", "Revenue"), *ORDERS]))]


def _count(term: str) -> int:
    """Whole-word occurrences in the CURRENT documents (version 2 of the policy; old versions are not searched)."""
    text = "\n".join([POLICY_V2, HR_FAQ, SUPPLIER_A, SUPPLIER_B, HINDI] + [" ".join(map(str, r)) for r in BIKRI] + [f"{d} {v}" for d, v in ORDERS])
    return len(re.findall(r"(?<!\w)" + r"\s+".join(map(re.escape, term.split())) + r"(?!\w)", text, re.I))


def dataset() -> EvalDataset:
    R = RelevantRef
    cases = [
        EvalCase(id="x01", question="How many days of annual leave do full-time employees accrue?", expected_route="semantic", relevant=[R(source="leave_policy.txt", contains="30 days of annual leave")],
                 expected_keywords=["30 days"], forbidden_keywords=["25 days"], expected_sources=["leave_policy.txt"]),
        EvalCase(id="x02", question="How many days a week is remote work allowed?", expected_route="semantic", relevant=[R(source="leave_policy.txt", contains="2 days per week")],
                 expected_keywords=["2 days"], forbidden_keywords=["3 days"]),
        EvalCase(id="x03", question="What changed in leave_policy.txt?", type="compare", expected_route="compare", expected_keywords=["25 → 30", "wellness stipend"], expected_sources=["leave_policy.txt"]),
        EvalCase(id="x04", question="Do leave_policy.txt and hr_faq.txt contradict each other?", type="contradiction", expected_route="compare",
                 expected_keywords=["candidate contradiction", "30 days", "28 days"], expected_sources=["leave_policy.txt", "hr_faq.txt"]),
        EvalCase(id="x05", question="Compare supplier_a.txt and supplier_b.txt", type="compare", expected_route="compare", expected_keywords=["Zenith Parts", "Acme Supplies"], expected_sources=["supplier_a.txt", "supplier_b.txt"]),
        EvalCase(id="x06", question='"छुट्टी" कितनी बार आया है', type="hindi", expected_route="exact", expected_count=_count("छुट्टी")),
        EvalCase(id="x07", question="कर्मचारियों को कितनी छुट्टी मिलती है", type="hindi", relevant=[R(source="hindi_policy.txt", contains="छुट्टी")], expected_keywords=["पच्चीस"], expected_sources=["hindi_policy.txt"]),
        EvalCase(id="x08", question="बिक्री का कुल योग क्या है?", type="hindi", expected_route="data", expected_value=float(sum(r[2] for r in BIKRI[1:]))),
        EvalCase(id="x09", question="सबसे अधिक बिक्री किस कर्मचारी की है?", type="hindi", expected_route="data", expected_keywords=["बीना"], expected_value=34000.0),
        EvalCase(id="x10", question="hindi_policy.txt का सारांश दें", type="hindi", expected_route="summarize", expected_keywords=["छुट्टी"]),
        EvalCase(id="x11", question="Show the monthly revenue trend", type="analytics", expected_route="data", expected_keywords=["trend up", "2024-06"]),
        EvalCase(id="x12", question="Are there any outliers in revenue?", type="analytics", expected_route="data", expected_keywords=["1 outlier", "9,000"]),
        EvalCase(id="x13", question='How many times does "Anjali Rao" appear, and what is the highest revenue?', type="parallel", expected_route="parallel",
                 expected_keywords=[f"Found {_count('Anjali Rao')} occurrence", "9,000"], expected_sources=["hr_faq.txt", "orders.csv"]),
        EvalCase(id="x14", question="What is the CEO's favourite colour?", type="abstain", answerable=False),
    ]
    return EvalDataset(name="platform-v3-extended", cases=cases)


def ingest(k, scope, workdir, owner_id: str = "anonymous") -> None:
    """Ingest the corpus in order (a repeated name becomes version 2)."""
    for i, (name, data) in enumerate(corpus()):
        path = workdir / f"{i}-{name}"
        path.write_bytes(data)
        r = k.ingest_file(scope, path, name, owner_id=owner_id)
        if r["status"] != "ready":
            raise RuntimeError(f"extended corpus: ingestion of {name} failed: {r['error']}")
