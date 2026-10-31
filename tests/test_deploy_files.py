"""Static checks of the deployment files. The Helm chart was NOT rendered here (no helm binary): these tests only catch gross mistakes
(unparseable YAML, template calls with unquoted keys, settings the app does not know)."""
import re
from pathlib import Path

import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "mka"


def test_chart_metadata_and_values_parse():
    assert yaml.safe_load((CHART / "Chart.yaml").read_text())["name"] == "mka"
    v = yaml.safe_load((CHART / "values.yaml").read_text())
    assert v["config"]["MKA_ENV"] == "production" and v["config"]["MKA_ALLOW_SIGNUP"] == "false" and v["persistence"]["accessMode"] == "ReadWriteMany"


def test_every_configured_mka_setting_exists_in_the_app():
    v = yaml.safe_load((CHART / "values.yaml").read_text())
    fields = {f.upper() for f in Settings.model_fields}
    for k in v["config"]:
        assert k.removeprefix("MKA_") in fields, k


def test_templates_use_quoted_dict_keys_and_balanced_actions():
    for f in (CHART / "templates").iterdir():
        t = f.read_text()
        assert t.count("{{") == t.count("}}"), f.name
        for m in re.finditer(r'\(dict ([^)]*(?:\([^)]*\)[^)]*)*)\)', t):
            keys = re.findall(r'(?:^|\s)("?\w+"?)\s+(?=[".\w(])', m.group(1))
            assert all(k.startswith('"') for k in keys[::2]), (f.name, m.group(1))


def test_secrets_are_referenced_not_embedded():
    blob = "".join(p.read_text() for p in CHART.rglob("*") if p.is_file())
    assert "existingSecret" in blob and not re.search(r"(?i)(password|api_key|jwt_secret)\s*:\s*\S{12,}", blob)
