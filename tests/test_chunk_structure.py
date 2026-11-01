from app.core import Unit
from app.ingestion.chunking import _is_heading, chunk_units

DOC = ("1. Leave policy\nEmployees accrue 25 days of annual leave per year.\n"
       "2. Expense policy\nExpense reports must be filed within 30 days of travel.\n"
       "3. Termination\nEither party may terminate with 60 days notice.")


def test_headings_are_detected_but_sentences_are_not():
    for h in ["1. Leave policy", "# Overview", "2.3 Payment terms", "Clause 8 Indemnity", "TERMS AND CONDITIONS", "Section 4"]:
        assert _is_heading(h), h
    for t in ["Employees accrue 25 days of annual leave per year.", "See the table below,", "ok", "x" * 150]:
        assert not _is_heading(t), t


def test_default_behaviour_is_unchanged():
    units = [Unit(DOC, {"page": 1})]
    assert [c.text for c in chunk_units(units, 1000, 100)] == [DOC]                      # one chunk, headings ignored


def test_structure_mode_starts_a_chunk_at_every_heading_and_keeps_original_unit_indexes():
    units = [Unit("intro paragraph", {"page": 1}), Unit(DOC, {"page": 2})]
    ch = chunk_units(units, 1000, 100, structure=True)
    texts = [c.text for c in ch]
    assert texts[1].startswith("1. Leave policy") and texts[2].startswith("2. Expense policy") and texts[3].startswith("3. Termination")
    assert all("Expense" not in t for t in (texts[1], texts[3]))
    assert all(c.u0 == c.u1 == (0 if "intro" in c.text else 1) for c in ch) and ch[1].loc == {"page": 2}


def test_long_section_pieces_repeat_the_heading():
    long = "4. Data protection\n" + ("The processor shall protect personal data carefully. " * 30)
    ch = chunk_units([Unit(long, {"page": 1})], 400, 50, structure=True)
    assert len(ch) > 2 and all(c.text.startswith("4. Data protection") for c in ch)
