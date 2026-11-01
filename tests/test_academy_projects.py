"""Every guided project ships complete, runnable files. This harness writes each one to a temp dir and runs ITS OWN tests
(trusted repo content, not learner code, so it runs directly rather than in the sandbox)."""
import subprocess
import sys

import pytest

from app.academy import service
from app.academy.content.projects import PROJECTS

IDS = [p["id"] for p in PROJECTS]


def test_ten_projects_with_unique_ids():
    assert len(PROJECTS) == 10 and len(set(IDS)) == 10


@pytest.mark.parametrize("p", PROJECTS, ids=IDS)
def test_structure(p):
    for key in ("title", "level", "hours", "stack", "prereq", "summary", "architecture", "folders", "steps", "files", "api_tests", "deploy", "interview"):
        assert p.get(key), f"{p['id']} missing {key}"
    nodes = set(p["architecture"]["nodes"])
    assert all(a in nodes and b in nodes for a, b in p["architecture"]["edges"])
    assert all(s.get("file") in p["files"] for s in p["steps"] if s.get("file"))
    lessons = service.lessons()
    assert all(x in lessons for x in p["prereq"]), p["prereq"]
    assert any(t.startswith("test_") for t in p["files"])


@pytest.mark.parametrize("p", PROJECTS, ids=IDS)
def test_project_tests_pass(p, tmp_path):
    for name, body in p["files"].items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-800:]


def test_extra_interview_categories_exist():
    from app.academy import catalog

    ids = {c[0] for c in catalog.CATEGORIES}
    assert all(x["category"] in ids for x in service.extra_interview())
