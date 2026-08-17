import json

from spse import paginate_list


class FakeDtSession:
    """Serves canned DataTables pages and records the bodies posted."""

    def __init__(self, pages):
        self.pages = pages
        self.bodies = []
        self.headers = {}

    def post(self, url, data=None, headers=None, timeout=None):
        self.bodies.append(data)
        index = len(self.bodies) - 1
        page = self.pages[index] if index < len(self.pages) else []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                # recordsTotal is Integer.MAX_VALUE in real responses.
                return {"draw": 1, "recordsTotal": 2147483647, "data": page}

        return Response()


def test_stops_on_empty_page():
    session = FakeDtSession([[["a"], ["b"]], []])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=2, log=lambda *a: None)
    assert rows == [["a"], ["b"]]
    assert len(session.bodies) == 2


def test_stops_on_short_page_without_extra_request():
    session = FakeDtSession([[["a"]]])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=10, log=lambda *a: None)
    assert rows == [["a"]]
    assert len(session.bodies) == 1


def test_ignores_records_total():
    # A naive implementation would try to fetch 2147483647 rows.
    session = FakeDtSession([[["a"], ["b"]], [["c"], ["d"]], []])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=2, log=lambda *a: None)
    assert len(rows) == 4


def test_advances_start_between_pages():
    session = FakeDtSession([[["a"], ["b"]], []])
    paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                  page_size=2, log=lambda *a: None)
    assert "start=0&" in session.bodies[0] + "&"
    assert "start=2&" in session.bodies[1] + "&"
