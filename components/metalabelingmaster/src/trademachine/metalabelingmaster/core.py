import pandas as pd
from trademachine.mt5.parser import MT5ReportParser


def process_report(filepath: str) -> pd.DataFrame:
    """
    Parses an MT5 report, extracts trades (entry, exit, PNL),
    and generates meta-labels.
    """
    parser = MT5ReportParser()
    expert_name = parser.parse_report(filepath)

    if not parser.deals_by_expert or expert_name not in parser.deals_by_expert:
        return pd.DataFrame()

    deals_df = parser.deals_by_expert[expert_name]

    # Filter out 'balance' deals
    df = deals_df[deals_df["Tipo"].str.lower() != "balance"].copy()

    trades = []
    current_in = None

    for _, row in df.iterrows():
        dir_val = str(row.get("Direção", "")).lower()

        if dir_val == "in":
            current_in = row
        elif dir_val in ("out", "in/out"):
            if current_in is not None:
                lucro_str = str(row.get("Lucro", "0")).replace(" ", "")
                try:
                    pnl = float(lucro_str)
                except ValueError:
                    pnl = 0.0

                trades.append(
                    {
                        "entry_time": current_in["Horário"],
                        "exit_time": row["Horário"],
                        "pnl": pnl,
                        "meta_label": 1 if pnl > 0 else 0,
                    }
                )
                current_in = None

    return pd.DataFrame(trades)
