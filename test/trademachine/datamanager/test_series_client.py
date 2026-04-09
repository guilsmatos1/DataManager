from __future__ import annotations

import pandas as pd
from trademachine.datamanager.client import DataManagerClient


class _DummyResponse:
    def __init__(self, *, json_data=None, content: bytes = b""):
        self._json_data = json_data
        self.content = content
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._json_data


class _DummySession:
    def __init__(self, responses: list[_DummyResponse]):
        self.responses = responses
        self.calls: list[tuple[str, str, object | None]] = []
        self.headers: dict[str, str] = {}
        self.timeout = None

    def get(self, url: str, params=None):
        self.calls.append(("GET", url, params))
        return self.responses.pop(0)

    def post(self, url: str, json=None):
        self.calls.append(("POST", url, json))
        return self.responses.pop(0)


def test_client_search_series(monkeypatch):
    session = _DummySession(
        [_DummyResponse(json_data={"series": [{"series_id": "CPIAUCSL"}]})]
    )
    monkeypatch.setattr("requests.Session", lambda: session)
    client = DataManagerClient(base_url="http://localhost:8686", api_key="test-key")

    result = client.search_series(query="inflation")

    assert result.loc[0, "series_id"] == "CPIAUCSL"
    assert session.calls == [
        (
            "GET",
            "http://localhost:8686/series/search",
            {"source": "fred", "query": "inflation"},
        )
    ]


def test_client_get_series_data(monkeypatch):
    df = pd.DataFrame(
        {"Value": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="D"),
    )
    session = _DummySession([_DummyResponse(content=b"ignored")])
    monkeypatch.setattr("requests.Session", lambda: session)
    monkeypatch.setattr(DataManagerClient, "_parse_parquet", lambda self, content: df)
    client = DataManagerClient(base_url="http://localhost:8686", api_key="test-key")

    result = client.get_series_data("fred", "CPIAUCSL")

    assert result["Value"].tolist() == [1.0, 2.0]
    assert session.calls == [
        ("GET", "http://localhost:8686/series/data/fred/CPIAUCSL", None)
    ]
