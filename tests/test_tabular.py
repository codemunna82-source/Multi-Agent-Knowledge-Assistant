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
