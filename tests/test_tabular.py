import pandas as pd

from .conftest import SALES_ROWS, ask, make_xlsx, upload


def csv_bytes(rows):
    return pd.DataFrame(rows[1:], columns=rows[0]).to_csv(index=False).encode()


def test_max_matches_manual_with_row_citation(client):
    upload(client, "sales.xlsx", make_xlsx({"Q1": SALES_ROWS}))
    r = ask(client, "Which employee has the highest sales?")
    assert r["route"] == "data" and r["details"]["result"]["value"] == 3400.5
    assert "Bob" in r["answer"] and "Dave" in r["answer"]  # tie is reported, not hidden
    assert sorted(c["location"] for c in r["citations"]) == ["sheet 'Q1', row 3", "sheet 'Q1', row 5"]


def test_sum_mean_count_filter_group(client):
    upload(client, "sales.csv", csv_bytes(SALES_ROWS))
    total = sum(x[2] for x in SALES_ROWS[1:])
    assert ask(client, "What is the total sales?")["details"]["result"]["value"] == total
    assert abs(ask(client, "What is the average sales?")["details"]["result"]["value"] - total / 5) < 1e-9
    assert ask(client, "How many employees are in the North region?")["details"]["result"]["value"] == 2
    assert ask(client, "total sales in the South region")["details"]["result"]["value"] == 6801.0
    r = ask(client, "Which region has the highest total sales?")
    assert "South" in r["answer"] and r["details"]["result"]["value"] == 6801.0
    assert ask(client, "How many employees have sales over 1000?")["details"]["result"]["value"] == 3
    assert "Eve" in ask(client, "Who has the lowest sales?")["answer"]


def test_ambiguous_numeric_column_asks(client):
    rows = [["Name", "Sales", "Cost"], ["a", 1, 2], ["b", 3, 4]]
    upload(client, "t.csv", csv_bytes(rows))
    r = ask(client, "What is the highest value?")
    assert r["needs_input"] and "Sales" in r["answer"]


def test_currency_formatting_is_parsed(client):
    upload(client, "m.csv", b'Name,Revenue\na,"$1,200.50"\nb,"$300"\n')
    assert ask(client, "total revenue")["details"]["result"]["value"] == 1500.5


def test_parsed_tables_are_cached_per_file_and_invalidated_when_the_file_changes(client):
    from app.tools import tabular as tab

    tab._CACHE.clear()
    k = client.app.state.knowledge
    from app.storage import Scope

    src = upload(client, "c.csv", b"Name,Sales\na,1\nb,2\n")["source"]
    st = k.store(Scope("default", "s1"))
    meta = st.get_source(src["id"])
    t1 = tab.load_tables(st, [meta])
    assert tab.load_tables(st, [meta])[0] is t1[0] and len(tab._CACHE) == 1                      # second call: no re-parse
    path = st.source_dir(src["id"]) / meta["original"]
    path.write_text("Name,Sales\na,1\nb,2\nc,3\n")                                                # file changed (re-index / replacement)
    t2 = tab.load_tables(st, [meta])
    assert t2[0] is not t1[0] and len(t2[0].df) == 3
    assert ask(client, "What is the total sales?")["details"]["result"]["value"] == 6
    for i in range(10):                                                                           # bounded: never more than CACHE_MAX_FILES entries
        s2 = upload(client, f"x{i}.csv", f"Name,Sales\na,{i}\n".encode())["source"]
        tab.load_tables(st, [st.get_source(s2["id"])])
    assert len(tab._CACHE) <= tab.CACHE_MAX_FILES
