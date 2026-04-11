# MetaLabelingMaster Project

## Overview
Parses MT5 reports and generates meta-labels (1 for profitable trades, 0 otherwise).

## Components
- `trademachine.metalabelingmaster` (component) -- core logic: `process_report(filepath)`
- `trademachine.mt5` (component) -- MT5 report parser
- `trademachine.metalabeling_master_cli` (base) -- CLI entry point

## Commands
```bash
# Run tests
uv run pytest components/metalabelingmaster/test/ -v
```
