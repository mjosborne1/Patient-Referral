import pytest

HCPD = "https://hcpd.test/fhir"
TOKEN_URL = "https://auth.test/oauth/token"
STATUS_URL = f"{HCPD}/$export-poll-status?_jobId=job-1"


@pytest.fixture
def http(requests_mock):
    return requests_mock


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now
