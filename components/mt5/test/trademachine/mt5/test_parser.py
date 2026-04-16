import pytest
from bs4 import BeautifulSoup
from trademachine.mt5.parser import MT5ReportParser

# ── Fixtures e Mocks ─────────────────────────────────────────────────────────


@pytest.fixture
def parser():
    return MT5ReportParser()


def test_extract_metadata_without_expert_advisor(parser):
    """If the report doesn't contain an 'Expert' row, it should handle gracefully."""
    html = """
    <html>
        <body>
            <table>
                <tr><td>Timeframe:</td><td>Daily</td></tr>
            </table>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    metadata = parser.extract_metadata(soup)
    assert "Expert_Advisor" not in metadata
    assert metadata["Timeframe"] == "Daily"


def test_extract_metadata_malformed_period(parser):
    """It should extract basic strings if regex fails for Period."""
    html = """
    <html>
        <body>
            <table>
                <tr><td>Period:</td><td>Something Weird</td></tr>
            </table>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    metadata = parser.extract_metadata(soup)
    assert metadata["Periodo_Inicial"] == "Something Weird"
    assert metadata["Periodo_Final"] == "Something Weird"


def test_extract_metadata_magic_number(parser):
    """It should extract MagicNumber if found in blank label."""
    html = """
    <html>
        <body>
            <table>
                <tr><td></td><td>MagicNumber=777</td></tr>
            </table>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    metadata = parser.extract_metadata(soup)
    assert metadata["Magic_Number"] == "777"


def test_extract_table_by_header_no_header_found(parser):
    """Should return an empty DataFrame if header is missing."""
    html = """<html><body><table><tr><td>Random</td></tr></table></body></html>"""
    soup = BeautifulSoup(html, "lxml")
    df = parser.extract_table_by_header(soup, "Deals")
    assert df.empty


def test_extract_table_by_header_corrupt_row(parser):
    """Should return empty row or handle colspan correctly in loop."""
    html = """
    <html>
        <body>
            <table>
                <tr><th>Deals</th></tr>
                <tr><td>Col1</td><td colspan="2">Col2</td></tr>
                <tr><td>Data1</td></tr>
            </table>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    df = parser.extract_table_by_header(soup, "Deals")
    assert not df.empty
    assert len(df.columns) == 3  # Col1, Col2, Col2_2
    assert df.iloc[0, 0] == "Data1"


def test_clean_deals_df_keeps_valid_date(parser):
    import pandas as pd

    df = pd.DataFrame(
        {
            "Horário": ["Horário", "2023.01.01 00:00:00", "Invalid", "2023.01.02"],
            "Tipo": ["Type", "BUY", "balance", "SELL"],
        }
    )
    cleaned = parser.clean_deals_df(df)
    # the first row is dropped, the third row matches 'balance'
    assert len(cleaned) == 3
    assert "Invalid" in cleaned["Horário"].values
