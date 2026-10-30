import pandas as pd
import pytest

from .conftest import ask, make_xlsx, upload

EMP = [["ID", "Name", "Dept", "Salary", "Email"],
       [1, "Alice", "Eng", 120000, "alice@x.io"], [2, "Bob", "Eng", 95000, "bob@x.io"], [3, "Carol", "Ops", 70000, "carol@x.io"],
       [4, "Dan", "Ops", 70000, "dan@x.io"], [5, "Erin", "HR", 82000, "Alice@x.io "], [6, "Frank", "HR", 60000, "frank@x.io"]]


def csv(rows):
    return pd.DataFrame(rows[1:], columns=rows[0]).to_csv(index=False).encode()


@pytest.fixture
def emp(client):
    upload(client, "emp.csv", csv(EMP))
    return client


def val(r):
    return r["details"]["result"]["value"]


def test_median_and_distinct(emp):
    assert val(ask(emp, "What is the median salary?")) == 76000.0
    r = ask(emp, "List the distinct Dept values")
    assert r["route"] == "data" and val(r) == 3 and "Eng (2)" in r["answer"] and "HR (2)" in r["answer"]


def test_sort_top_n_with_row_citations(emp):
    r = ask(emp, "Show the top 3 employees sorted by salary")
    assert [c["location"] for c in r["citations"]] == ["row 2", "row 3", "row 6"]  # Alice 120k, Bob 95k, Erin 82k
    assert "descending" in r["answer"]
    r = ask(emp, "sort by salary ascending, bottom 2")
    assert [c["location"] for c in r["citations"]] == ["row 7", "row 4"]  # Frank 60k, Carol 70k (stable)


def test_sort_with_filter(emp):
    r = ask(emp, "top 2 salary in Ops")
    assert len(r["citations"]) == 2 and all("Ops" in c["excerpt"] for c in r["citations"])


def test_duplicate_detection_whole_row_and_column(emp):
    r = ask(emp, "Are there duplicate emails?")  # Alice@x.io  == alice@x.io (case/space-insensitive)
    d = r["details"]["result"]
    assert d["value"] == 1 and sorted(d["duplicate_groups"][0]["rows"]) == [2, 6] and r["route"] == "data"
    assert {c["location"] for c in r["citations"]} == {"row 2", "row 6"}
    assert "No duplicate rows" in ask(emp, "Are there duplicate rows?")["answer"]  # whole-row duplicates: none
    upload(emp, "dupes.csv", csv([["a", "b"], [1, "x"], [1, "x"], [2, "y"]]))
    r = ask(emp, "find duplicate rows in dupes.csv")
    assert r["details"]["result"]["value"] == 1


def test_compare_two_tables(client):
    left = [["ID", "Name", "Salary"], [1, "Alice", 100], [2, "Bob", 90], [3, "Carol", 80]]
    right = [["ID", "Name", "Salary", "Bonus"], [1, "Alice", 100, 5], [2, "Bob", 95, 5], [4, "Dan", 70, 5]]
    upload(client, "left.csv", csv(left))
    upload(client, "right.xlsx", make_xlsx({"Sheet1": right}))
    r = ask(client, "Compare the data in left.csv and right.xlsx")
    assert r["route"] == "data"
    d = r["details"]["result"]["diff"]
    assert (d["only_left_count"], d["only_right_count"], d["changed_count"], d["same_count"]) == (1, 1, 1, 1)
    assert d["changed"][0]["diff"] == {"Salary": [90, 95]} or d["changed"][0]["diff"] == {"Salary": (90, 95)}
    assert d["cols_only_right"] == ["Bonus"] and d["key"] == "ID"
    assert "Carol" in str(d) or d["only_left"] == ["3"]
    locs = {c["location"] for c in r["citations"]}
    assert "row 4" in locs and "sheet 'Sheet1', row 4" in locs


def test_compare_needs_a_key(client):
    upload(client, "a.csv", csv([["x", "y"], [1, 1], [1, 2]]))
    upload(client, "b.csv", csv([["x", "z"], [1, 1], [1, 2]]))
    r = ask(client, "compare the tables a.csv and b.csv")
    assert r["needs_input"] and "key" in r["answer"].lower()


def test_ambiguous_still_asks_instead_of_guessing(emp):
    upload(emp, "two.csv", csv([["Name", "A", "B"], ["x", 1, 2]]))
    r = ask(emp, "sort two.csv by value")
    assert r["needs_input"]
