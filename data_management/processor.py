import pandas as pd

class DataProcessor:
    """Utility class for converting OHLC timeframes."""
    
    # Mapping of common abbreviations to pandas resample rules
    TF_MAPPING = {
        'M1': '1min',
        'M2': '2min',
        'M5': '5min',
        'M10': '10min',
        'M15': '15min',
        'M30': '30min',
        'H1': '1h',
        'H2': '2h',
        'H3': '3h',
        'H4': '4h',
        'H6': '6h',
        'D1': 'D',
        'W1': 'W',
    }

    @classmethod
    def resample_ohlc(cls, df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """
        Takes an OHLCV DataFrame (lower timeframe, e.g. M1) and converts it to a higher timeframe.
        """
        if target_timeframe.upper() not in cls.TF_MAPPING:
            raise ValueError(f"Target timeframe not supported: {target_timeframe}. Use {list(cls.TF_MAPPING.keys())}")
            
        rule = cls.TF_MAPPING[target_timeframe.upper()]
        
        # Map aggregation dictionaries
        # Assumes lowercase columns as default in openbb/dukascopy returns
        # We will do flexible column validation
        cols = {c.lower(): c for c in df.columns}
        
        agg_dict = {}
        if 'open' in cols: agg_dict[cols['open']] = 'first'
        if 'high' in cols: agg_dict[cols['high']] = 'max'
        if 'low' in cols: agg_dict[cols['low']] = 'min'
        if 'close' in cols: agg_dict[cols['close']] = 'last'
        if 'volume' in cols: agg_dict[cols['volume']] = 'sum'
            
        if not agg_dict:
            raise ValueError("The DataFrame does not contain valid OHLC columns for resampling.")
            
        resampled_df = df.resample(rule).agg(agg_dict).dropna()
        return resampled_df
