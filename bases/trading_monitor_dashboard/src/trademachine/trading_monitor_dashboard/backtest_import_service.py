from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

import pandas as pd
from bs4 import BeautifulSoup
from fastapi import UploadFile
from sqlalchemy.orm import Session
from trademachine.mt5.parser import (
    _EN_TO_PT_COLUMNS,
    MT5ReportParser,
)
from trademachine.tradingmonitor_storage.public import (
    Backtest,
    BacktestDeal,
    BacktestEquity,
    DealType,
    Strategy,
    Symbol,
)

logger = logging.getLogger(__name__)

_DEAL_TYPE_MAP = {
    "buy": DealType.BUY,
    "sell": DealType.SELL,
    "balance": DealType.BALANCE,
}


class BacktestImportError(Exception):
    pass


def _soup_from_bytes(content: bytes) -> BeautifulSoup:
    for encoding in ("utf-16", "utf-8", "latin-1"):
        try:
            return BeautifulSoup(content.decode(encoding), "lxml")
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise BacktestImportError(
        "Não foi possível decodificar o arquivo HTML (tentativas: utf-16, utf-8, latin-1)"
    )


def _parse_mt5_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y.%m.%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_mt5_timestamp(ts_str: str) -> datetime | None:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(ts_str.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _first_col(df: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def _to_float(val: str, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return default


def _to_int(val: str, default: int = 0) -> int:
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


def _parse_deal_type(raw: str) -> DealType | None:
    return _DEAL_TYPE_MAP.get(raw.strip().lower())


def _import_deals(
    db: Session,
    backtest_id: int,
    deals_df: pd.DataFrame,
    symbol: str | None,
    col_ts: str | None,
    col_ticket: str | None,
    col_symbol: str | None,
    col_tipo: str | None,
    col_vol: str | None,
    col_price: str | None,
    col_comm: str | None,
    col_swap: str | None,
    col_profit: str | None,
    col_balance: str | None,
) -> int:
    deals_imported = 0
    for _, row in deals_df.iterrows():
        ts_raw = row[col_ts] if col_ts else ""
        ts = _parse_mt5_timestamp(str(ts_raw))
        if ts is None:
            continue

        tipo_raw = str(row[col_tipo]) if col_tipo else ""
        deal_type = _parse_deal_type(tipo_raw)
        if deal_type is None:
            continue

        ticket = _to_int(row[col_ticket]) if col_ticket else 0
        row_symbol = (
            str(row[col_symbol]).strip()
            if col_symbol and row[col_symbol]
            else (symbol or "")
        )
        volume = _to_float(row[col_vol]) if col_vol else 0.0
        price = _to_float(row[col_price]) if col_price else 0.0
        commission = _to_float(row[col_comm]) if col_comm else 0.0
        swap = _to_float(row[col_swap]) if col_swap else 0.0
        profit = _to_float(row[col_profit]) if col_profit else 0.0
        balance = _to_float(row[col_balance]) if col_balance else 0.0

        db.add(
            BacktestDeal(
                backtest_id=backtest_id,
                timestamp=ts,
                ticket=ticket,
                symbol=row_symbol,
                type=deal_type,
                volume=volume,
                price=price,
                profit=profit,
                commission=commission,
                swap=swap,
            )
        )
        if col_balance:
            db.add(
                BacktestEquity(
                    backtest_id=backtest_id,
                    timestamp=ts,
                    balance=balance,
                    equity=balance,
                )
            )
        deals_imported += 1
    return deals_imported


async def process_html_upload(
    upload_file: UploadFile,
    magic_number_override: str | None,
    db: Session,
    parser: MT5ReportParser,
) -> dict:
    result: dict = {
        "filename": upload_file.filename,
        "status": "ok",
        "backtest_id": None,
        "deals_imported": 0,
        "error": None,
    }
    try:
        content = await upload_file.read()
        soup = _soup_from_bytes(content)
        metadata = parser.extract_metadata(soup)

        magic_number = magic_number_override or metadata.get("Magic_Number")
        if not magic_number:
            raise BacktestImportError("Magic Number não encontrado no relatório")

        strategy = db.query(Strategy).filter(Strategy.id == magic_number).first()
        if not strategy:
            raise BacktestImportError(
                f"Estratégia com Magic Number {magic_number} não cadastrada"
            )

        report_name = metadata.get("Expert_Advisor")
        if report_name:
            strategy.name = report_name
        if not strategy.timeframe:
            report_tf = metadata.get("Timeframe")
            if report_tf:
                strategy.timeframe = report_tf
        db.flush()

        client_run_id = int(hashlib.md5(content).hexdigest()[:15], 16)  # noqa: S324

        existing = (
            db.query(Backtest)
            .filter(
                Backtest.strategy_id == magic_number,
                Backtest.client_run_id == client_run_id,
            )
            .first()
        )
        if existing:
            db.commit()
            result["status"] = "skipped"
            result["backtest_id"] = existing.id
            result["error"] = "Relatório já importado anteriormente"
            return result

        deals_df = parser.extract_table_by_header(soup, "Transações")
        if deals_df.empty:
            deals_df = parser.extract_table_by_header(soup, "Deals")
            if not deals_df.empty:
                deals_df = deals_df.rename(columns=_EN_TO_PT_COLUMNS)
        if deals_df.empty:
            raise BacktestImportError(
                "Tabela de transações não encontrada no relatório"
            )

        deals_df = parser.clean_deals_df(deals_df)

        col_ts = _first_col(deals_df, "Horário", "Time")
        col_ticket = _first_col(deals_df, "Posição", "Position", "Ticket", "#")
        col_symbol = _first_col(deals_df, "Símbolo", "Symbol")
        col_tipo = _first_col(deals_df, "Tipo", "Type")
        col_vol = _first_col(deals_df, "Volume")
        col_price = _first_col(deals_df, "Preço", "Price")
        col_comm = _first_col(deals_df, "Comissão", "Commission")
        col_swap = _first_col(deals_df, "Swap")
        col_profit = _first_col(deals_df, "Lucro", "Profit")
        col_balance = _first_col(deals_df, "Saldo", "Balance")

        if not col_ts or not col_tipo:
            raise BacktestImportError(
                "Colunas obrigatórias (Horário, Tipo) não encontradas"
            )

        initial_balance: float | None = None
        if col_balance is not None:
            balance_rows = deals_df[
                deals_df[col_tipo].str.strip().str.lower() == "balance"
            ]
            if not balance_rows.empty:
                initial_balance = _to_float(balance_rows.iloc[0][col_balance])

        start_dt = _parse_mt5_date(metadata.get("Periodo_Inicial"))
        end_dt = _parse_mt5_date(metadata.get("Periodo_Final"))
        symbol = metadata.get("Ativo")
        symbol_id = None
        if symbol:
            symbol_row = db.query(Symbol).filter(Symbol.name == symbol).first()
            if symbol_row is None:
                symbol_row = Symbol(name=symbol)
                db.add(symbol_row)
                db.flush()
            symbol_id = symbol_row.id

        backtest = Backtest(
            strategy_id=magic_number,
            client_run_id=client_run_id,
            name=metadata.get("Expert_Advisor") or upload_file.filename,
            symbol=symbol,
            symbol_id=symbol_id,
            start_date=start_dt,
            end_date=end_dt,
            initial_balance=initial_balance,
            status="complete",
        )
        db.add(backtest)
        db.flush()

        deals_imported = _import_deals(
            db,
            backtest.id,
            deals_df,
            symbol,
            col_ts,
            col_ticket,
            col_symbol,
            col_tipo,
            col_vol,
            col_price,
            col_comm,
            col_swap,
            col_profit,
            col_balance,
        )

        db.commit()
        result["backtest_id"] = backtest.id
        result["deals_imported"] = deals_imported

    except BacktestImportError as exc:
        db.rollback()
        result["status"] = "error"
        result["error"] = str(exc)
    except Exception as exc:
        db.rollback()
        logger.exception("Erro ao processar upload: %s", upload_file.filename)
        result["status"] = "error"
        result["error"] = str(exc)

    return result
