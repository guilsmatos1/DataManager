from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from datamanager.client import DataManagerClient


@pytest.fixture
def client():
    return DataManagerClient(base_url="http://testserver", api_key="test-key")


def test_init(client):
    assert client.base_url == "http://testserver"
    assert client.session.headers["X-API-Key"] == "test-key"


def test_download(client):
    with patch.object(client.session, "post") as mock_post:
        mock_post.return_value.json.return_value = {"status": "success"}
        mock_post.return_value.raise_for_status = MagicMock()

        res = client.download("DUKASCOPY", "EURUSD", "2023-01-01", "2023-01-02")

        assert res["status"] == "success"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["source"] == "DUKASCOPY"


def test_update(client):
    with patch.object(client.session, "post") as mock_post:
        mock_post.return_value.json.return_value = {"status": "success"}
        res = client.update("DUKASCOPY", "EURUSD", "M1")
        assert res["status"] == "success"
        mock_post.assert_called_once()


def test_list_databases(client):
    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value.json.return_value = {"databases": [{"asset": "EURUSD"}]}
        dbs = client.list_databases()
        assert len(dbs) == 1
        assert dbs[0]["asset"] == "EURUSD"


def test_get_data_df(client):
    # Mock parquet data
    df = pd.DataFrame({"Open": [1.0]}, index=pd.date_range("2023-01-01", periods=1))
    pq_data = BytesIO()
    df.to_parquet(pq_data)

    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value.content = pq_data.getvalue()
        mock_get.return_value.raise_for_status = MagicMock()

        result_df = client.get_data("DUKASCOPY", "EURUSD", "M1")
        assert isinstance(result_df, pd.DataFrame)
        assert len(result_df) == 1


def test_get_data_save_file(client, tmp_path):
    df = pd.DataFrame({"Open": [1.0]}, index=pd.date_range("2023-01-01", periods=1))
    pq_data = BytesIO()
    df.to_parquet(pq_data)

    save_path = tmp_path / "test.parquet"

    with patch.object(client.session, "get") as mock_get:
        mock_get.return_value.content = pq_data.getvalue()
        mock_get.return_value.raise_for_status = MagicMock()

        res_path = client.get_data("DUKASCOPY", "EURUSD", "M1", save_path=str(save_path))
        assert res_path == str(save_path)
        assert save_path.exists()


def test_apply_timezone(client):
    dates = pd.date_range("2023-01-01 12:00:00", periods=1, freq="h")
    df = pd.DataFrame({"Open": [1.0]}, index=dates)

    # Client expects naive UTC index
    df_tz = client._apply_timezone(df, "America/Sao_Paulo")
    # UTC 12:00 -> Sao Paulo 09:00 (for Jan, offset is -3)
    assert df_tz.index[0].hour == 9
    assert str(df_tz.index.tz) == "America/Sao_Paulo"


def test_handle_response_error(client):
    mock_res = MagicMock()
    import requests

    mock_res.raise_for_status.side_effect = requests.exceptions.HTTPError("Bad Request")
    mock_res.json.return_value = {"detail": "Specific error message"}

    with pytest.raises(RuntimeError, match="Specific error message"):
        client._handle_response(mock_res)
