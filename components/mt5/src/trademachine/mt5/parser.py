"""
MT5 Parser Module
=================
Contains the MT5ReportParser class for extracting data from MT5 HTML reports.
"""

import logging
import os
import re

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Raised when an MT5 report cannot be parsed."""


# Matches the date range "(YYYY.MM.DD - YYYY.MM.DD)" found in the Period field.
# Example: "(2023.01.01 - 2024.12.31)"
_DATE = r"\d{4}\.\d{2}\.\d{2}"
DATE_RANGE_PATTERN = rf"\((?P<start>{_DATE})\s*-\s*(?P<end>{_DATE})\)"

_RE_DATE_RANGE = re.compile(DATE_RANGE_PATTERN)
_RE_DATE = re.compile(r"\d{4}\.\d{2}\.\d{2}")

# EN→PT column rename map for English MT5 reports.
# Row values (buy/sell/balance, out/in/in/out) are identical in both locales.
_EN_TO_PT_COLUMNS = {
    "Time": "Horário",
    "Type": "Tipo",
    "Direction": "Direção",
    "Volume": "Volume",
    "Profit": "Lucro",
    "Balance": "Saldo",
    "Commission": "Comissão",
}


class MT5ReportParser:
    """Class for extracting and manipulating data from MT5 reports."""

    def __init__(self):
        self.deals_by_expert = {}

    def read_html_report(self, filepath: str) -> BeautifulSoup:
        """Reads MT5 report HTML (supports UTF-16, UTF-8, and Latin-1)."""
        encodings = ("utf-16", "utf-8", "latin-1")
        for encoding in encodings:
            try:
                with open(filepath, "rb") as f:
                    content = f.read()
                html = content.decode(encoding)
                # Use 'lxml' for significant performance boost on large reports
                return BeautifulSoup(html, "lxml")
            except (UnicodeDecodeError, UnicodeError):
                logger.debug(
                    f"Failed to decode '{filepath}' as {encoding}, trying next."
                )
        raise ValueError(
            f"Could not decode '{filepath}' in any supported encoding "
            f"(tried: {', '.join(encodings)})."
        )

    def _parse_period_cell(self, text: str, metadata: dict) -> None:
        match = re.search(DATE_RANGE_PATTERN, text)
        if match:
            metadata["Periodo_Inicial"] = match.group("start")
            metadata["Periodo_Final"] = match.group("end")
        else:
            metadata["Periodo_Inicial"] = text
            metadata["Periodo_Final"] = text
        tf = re.split(r"[\s(]", text)[0].strip()
        if tf and not re.match(r"\d{4}\.\d{2}\.\d{2}", tf):
            metadata["Timeframe"] = tf

    def _process_metadata_row(
        self, label_text: str, cells: list, metadata: dict
    ) -> None:
        if "Expert Advisor" in label_text or "Expert" in label_text:
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text:
                    metadata["Expert_Advisor"] = text
                    break

        elif label_text in ("Ativo:", "Symbol:"):
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text:
                    metadata["Ativo"] = text
                    break

        elif "Período:" in label_text or "Period:" in label_text:
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text:
                    self._parse_period_cell(text, metadata)
                    break

        elif "Timeframe:" in label_text or label_text == "Timeframe":
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text:
                    tf = re.split(r"[\s(]", text)[0].strip()
                    if tf:
                        metadata["Timeframe"] = tf
                    break

        elif not label_text:
            for cell in cells[1:]:
                text = cell.get_text(strip=True)
                if text.startswith("MagicNumber="):
                    metadata["Magic_Number"] = text.split("=", 1)[1]

    def extract_metadata(self, soup: BeautifulSoup) -> dict:
        """Extracts metadata from the 'Configuration' section of the report.
        Optimized to stop searching once configuration data is found.
        """
        metadata: dict[str, str] = {}
        # Configuration is always at the top, no need to search all <tr>s
        rows = soup.find_all("tr", limit=100)

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label_text = cells[0].get_text(strip=True)
            self._process_metadata_row(label_text, cells, metadata)

        return metadata

    def _find_header_node(self, soup: BeautifulSoup, header_name: str):
        """Returns the first th/td node whose text exactly matches header_name, or None.
        Optimized to search in chunks or use more specific finders.
        """
        # Deals tables headers are usually in <th> or <td> inside <tr>
        return soup.find(
            lambda tag: tag.name in ("th", "td")
            and tag.get_text(strip=True) == header_name
        )

    def _extract_columns(self, column_row) -> list[str]:
        """Builds the column name list from a header <tr>, expanding colspan cells."""
        columns = []
        for cell in column_row.find_all(["td", "th"]):
            col_text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            columns.append(col_text)
            for extra in range(1, colspan):
                columns.append(f"{col_text}_{extra + 1}")
        return columns

    def _extract_data_rows(self, column_row, num_columns: int) -> list[list[str]]:
        """Collects all data <tr> rows that follow the column header row."""
        data_rows = []
        current_row = column_row.find_next_sibling("tr")

        while current_row:
            cells = current_row.find_all("td")
            if not cells:
                break
            if current_row.find("th"):
                break

            row_data = []
            for cell in cells:
                colspan = int(cell.get("colspan", 1))
                row_data.append(cell.get_text(strip=True))
                for _ in range(1, colspan):
                    row_data.append("")

            if len(row_data) < num_columns:
                row_data.extend([""] * (num_columns - len(row_data)))
            data_rows.append(row_data[:num_columns])
            current_row = current_row.find_next_sibling("tr")

        return data_rows

    def extract_table_by_header(
        self, soup: BeautifulSoup, header_name: str
    ) -> pd.DataFrame:
        """Generic function to extract MT5 tables based on header text."""
        header_node = self._find_header_node(soup, header_name)
        if header_node is None:
            return pd.DataFrame()

        header_tr = header_node.find_parent("tr")
        if header_tr is None:
            return pd.DataFrame()
        column_tr = header_tr.find_next_sibling("tr")
        if column_tr is None:
            return pd.DataFrame()

        columns = self._extract_columns(column_tr)
        data_rows = self._extract_data_rows(column_tr, len(columns))

        df = pd.DataFrame(data_rows, columns=columns)
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].str.replace("\xa0", " ", regex=False).str.strip()

        return df

    def clean_deals_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Removes repeated header rows and non-timestamped rows from the deals table.

        Must be called after EN→PT column rename so 'Horário' and 'Tipo' are present.
        """
        if "Horário" not in df.columns or "Tipo" not in df.columns:
            return df
        df = df[df["Horário"] != "Horário"]
        # Filter: Keep rows with a valid date OR 'balance' type.
        # Ensure we don't accidentally drop trade rows that have the lot info.
        df = df[
            df["Horário"].str.contains(r"\d{4}\.\d{2}\.\d{2}", na=False)
            | (df["Tipo"].str.lower() == "balance")
        ]
        return df

    def parse_report(self, filepath: str) -> str:
        """Processes an MT5 HTML report and stores the deals DataFrame."""
        soup = self.read_html_report(filepath)

        metadata = self.extract_metadata(soup)

        if "Expert_Advisor" not in metadata:
            fallback_name = os.path.splitext(os.path.basename(filepath))[0]
            logger.warning(
                f"Expert Advisor name not found in '{filepath}'. "
                f"Using filename as strategy name: '{fallback_name}'"
            )
            expert_name = fallback_name
        else:
            expert_name = metadata["Expert_Advisor"]

        deals_df = self.extract_table_by_header(soup, "Transações")
        if deals_df.empty:
            deals_df = self.extract_table_by_header(soup, "Deals")
            if not deals_df.empty:
                deals_df = deals_df.rename(columns=_EN_TO_PT_COLUMNS)
        if deals_df.empty:
            raise ParserError(
                f"No deals table found in '{filepath}' (tried PT and EN headers)."
            )

        # Clean after any rename so 'Horário'/'Tipo' are guaranteed to exist
        self.deals_by_expert[expert_name] = self.clean_deals_df(deals_df)

        return expert_name
