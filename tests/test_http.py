import pytest

from spse import extract_token, fetch_html, listing_url

HTML_WITH_TOKEN = """
<script>
  var authenticityToken = 'abc123def456';
</script>
"""


class FakeResponse:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text

    def json(self):
        return {"data": []}


class FakeSession:
    """Records the requests made so tests can assert on headers."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or [FakeResponse()]
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def test_extract_token():
    assert extract_token(HTML_WITH_TOKEN) == "abc123def456"


def test_extract_token_raises_with_snippet():
    with pytest.raises(RuntimeError) as err:
        extract_token("<html>Akses Ditolak</html>")
    assert "Akses Ditolak" in str(err.value)


def test_fetch_html_sends_referer():
    # Detail pages return 403 without a Referer, so it must always be sent.
    session = FakeSession()
    fetch_html(session, "https://spse.inaproc.id/kemkes/lelang/1/peserta",
               referer="https://spse.inaproc.id/kemkes/lelang?tahun=2025")
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["Referer"] == "https://spse.inaproc.id/kemkes/lelang?tahun=2025"


def test_fetch_html_returns_none_on_403_without_retrying_forever():
    session = FakeSession([FakeResponse(403, "Akses Ditolak!")])
    assert fetch_html(session, "https://x/y", referer="https://x", retries=1) is None


def test_listing_url_is_the_canonical_referer_shape():
    # listing_url doubles as the mandatory Referer for detail requests; a
    # wrong shape breaks detail fetching with 403s and no other signal.
    assert listing_url("https://spse.inaproc.id/kemkes", "tender", 2025) == \
        "https://spse.inaproc.id/kemkes/lelang?tahun=2025"
    assert listing_url("https://spse.inaproc.id/kemkes", "swakelola", 2025) == \
        "https://spse.inaproc.id/kemkes/swakelola?tahun=2025"
