import pytest

BASE = "https://fhir.test/fhir"


def searchset(*resources):
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"resource": r} for r in resources]}


def transaction_response(n):
    return {"resourceType": "Bundle", "type": "transaction-response",
            "entry": [{"response": {"status": "201 Created"}} for _ in range(n)]}


@pytest.fixture
def fhir(requests_mock):
    """A fake FHIR server at BASE; register responses on it per test."""
    return requests_mock


@pytest.fixture
def client():
    import os
    os.environ["TESTING"] = "true"
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


FHIR_HEADERS = {"X-FHIR-Server-URL": BASE}
