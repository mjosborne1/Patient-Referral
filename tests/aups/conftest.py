import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://fhir.test/fhir"
HEADERS = {"X-FHIR-Server-URL": BASE}


def load(name):
    """Load one of the HL7 AU test data set AU PS bundles (au-fhir-test-data, CC0)."""
    return json.loads((FIXTURES / f"Bundle-aups-{name}.json").read_text())


@pytest.fixture
def client():
    os.environ["TESTING"] = "true"
    from app import app
    app.config["TESTING"] = True
    app.config["LOGIN_DISABLED"] = True
    with app.test_client() as c:
        yield c
