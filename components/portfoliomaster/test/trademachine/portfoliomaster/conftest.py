import glob
import os

import pytest
from trademachine.mt5.parser import MT5ReportParser
from trademachine.portfoliomaster.services.portfolio import PortfolioManager

pytestmark = pytest.mark.integration

_TEST_DIR = os.path.dirname(__file__)
REPORTS_DIR = os.path.join(_TEST_DIR, "reports")
REPORTS_EN_DIR = os.path.join(_TEST_DIR, "reports-en")


@pytest.fixture(scope="session")
def pt_report_files():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*.html")))
    assert files, "No HTML files found in tests/reports/"
    return files


@pytest.fixture(scope="session")
def en_report_files():
    files = sorted(glob.glob(os.path.join(REPORTS_EN_DIR, "*.html")))
    assert files, "No HTML files found in tests/reports-en/"
    return files


@pytest.fixture(scope="session")
def pt_parser(pt_report_files):
    """MT5ReportParser with up to 10 PT reports pre-parsed (shared across session)."""
    parser = MT5ReportParser()
    for filepath in pt_report_files[:10]:
        parser.parse_report(filepath)
    return parser


@pytest.fixture(scope="session")
def en_parser(en_report_files):
    """MT5ReportParser with up to 10 EN reports pre-parsed (shared across session)."""
    parser = MT5ReportParser()
    for filepath in en_report_files[:10]:
        parser.parse_report(filepath)
    return parser


@pytest.fixture(scope="session")
def loaded_manager(pt_parser):
    """PortfolioManager with up to 5 real strategies loaded (shared across session)."""
    pm = PortfolioManager()
    for name in list(pt_parser.deals_by_expert.keys())[:5]:
        pm.add_strategy(name, pt_parser.deals_by_expert[name])
    return pm
