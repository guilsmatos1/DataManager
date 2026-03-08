from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Any
from core.server import DataManager
from datetime import datetime
from fastapi.responses import FileResponse
import os
from pathlib import Path

app = FastAPI(title="DataManager Network API", version="1.0.0")
manager = DataManager()

class DownloadRequest(BaseModel):
    source: str
    asset: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class UpdateRequest(BaseModel):
    source: str
    asset: str
    timeframe: str = "M1"

class DeleteRequest(BaseModel):
    source: str
    asset: str
    timeframe: Optional[str] = None

class ResampleRequest(BaseModel):
    source: str
    asset: str
    target_timeframe: str

@app.post("/download")
def download_data(req: DownloadRequest):
    try:
        start_dt = datetime.fromisoformat(req.start_date) if req.start_date else datetime(2000, 1, 1)
        end_dt = datetime.fromisoformat(req.end_date) if req.end_date else datetime.now()
        
        # Multiple assets download support based on CLI logic
        assets = [a.strip() for a in req.asset.split(',') if a.strip()]
        for asset in assets:
            manager.download_data(req.source, asset, start_dt, end_dt)
        return {"status": "success", "message": f"Download initiated/completed for {req.asset} via {req.source}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/update")
def update_data(req: UpdateRequest):
    try:
        assets = [a.strip() for a in req.asset.split(',') if a.strip()]
        for asset in assets:
            manager.update_data(req.source, asset, req.timeframe)
        return {"status": "success", "message": f"Update completed for {req.asset} via {req.source} ({req.timeframe})"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/delete")
def delete_data(req: DeleteRequest):
    try:
        if req.source.lower() == 'all' and req.asset.lower() == 'all':
            manager.delete_all_databases()
            return {"status": "success", "message": "All databases deleted"}
            
        assets = [a.strip() for a in req.asset.split(',') if a.strip()]
        for asset in assets:
            manager.delete_database(req.source, asset, req.timeframe)
        target = req.timeframe if req.timeframe else "all timeframes"
        return {"status": "success", "message": f"Deleted {req.asset} from {req.source} ({target})"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/list")
def list_databases():
    try:
        dbs = manager.list_all()
        return {"databases": dbs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/info/{source}/{asset}/{timeframe}")
def get_info(source: str, asset: str, timeframe: str):
    info = manager.info(source, asset, timeframe)
    if info.get("status") == "Not Found":
        raise HTTPException(status_code=404, detail="Database not found")
    return info
    
@app.get("/search")
def search_assets(source: str = "openbb", query: Optional[str] = None, exchange: Optional[str] = None):
    # This is a bit tricky as search prints out. We will capture the output or re-implement logic here cleanly
    source = source.lower()
    if source == "dukascopy":
        csv_path = Path("database") / "dukas_assets.csv"
        if not csv_path.exists():
            return {"assets": []}
        import pandas as pd
        df = pd.read_csv(csv_path).fillna("")
        if query:
            mask = (df['ticker'].str.contains(query, case=False) |
                    df['alias'].str.contains(query, case=False) |
                    df['nome_do_ativo'].str.contains(query, case=False))
            df = df[mask]
        return {"assets": df.to_dict(orient="records")}
    else:
        # OpenBB search returns a DF internally, we would need to call `res = obb.equity.search(**kwargs)`
        try:
            from openbb import obb
            kwargs = {}
            if query: kwargs['query'] = query
            if exchange: kwargs['exchange'] = exchange
            res = obb.equity.search(**kwargs)
            df = res.to_df().reset_index().fillna("")
            return {"assets": df.to_dict(orient="records")}
        except Exception as e:
             raise HTTPException(status_code=500, detail=f"OpenBB search error: {str(e)}")

@app.post("/resample")
def resample_data(req: ResampleRequest):
    try:
        manager.resample_database(req.source, req.asset, req.target_timeframe)
        return {"status": "success", "message": f"Resampled {req.asset} to {req.target_timeframe}"}
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@app.get("/data/{source}/{asset}/{timeframe}")
def get_data_file(source: str, asset: str, timeframe: str):
    """Retorna o arquivo Parquet real para ser lido sobre a rede."""
    file_path = manager.storage._get_path(source, asset, timeframe)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Data file not found")
        
    return FileResponse(
        path=file_path, 
        media_type='application/octet-stream', 
        filename=f"{source}_{asset}_{timeframe}.parquet"
    )

if __name__ == "__main__":
    import uvicorn
    print("Iniciando DataManager Network API...")
    uvicorn.run(app, host="0.0.0.0", port=8686)
