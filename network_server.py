from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from core.server import DataManager
from datetime import datetime
from fastapi.responses import FileResponse
import os
import re
from pathlib import Path

app = FastAPI(title="DataManager Network API", version="1.0.0")
manager = DataManager()

# --- SEGURANÇA: 1. Authentication via API Key ---
API_KEY_NAME = "X-API-Key"
API_KEY = os.getenv("DATAMANAGER_API_KEY", "YOUR_API_KEY_HERE")
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(api_key: str = Security(api_key_header)):
    if api_key == API_KEY:
        return api_key
    raise HTTPException(status_code=403, detail="Access denied: Invalid API Key")

# --- SEGURANÇA: 2. Validation against Path Traversal ---
SAFE_PATTERN = r"^[a-zA-Z0-9_,\s\-]+$"

class DownloadRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class UpdateRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: str = Field("M1", pattern=r"^[a-zA-Z0-9_]+$")

class DeleteRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    timeframe: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_]+$")

class ResampleRequest(BaseModel):
    source: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    asset: str = Field(..., pattern=SAFE_PATTERN)
    target_timeframe: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")

# --- SEGURANÇA: 3. Asynchronous tasks (BackgroundTasks) to avoid blocking the server ---

@app.post("/download")
def download_data(req: DownloadRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    try:
        start_dt = datetime.fromisoformat(req.start_date) if req.start_date else datetime(2000, 1, 1)
        end_dt = datetime.fromisoformat(req.end_date) if req.end_date else datetime.now()
        
        assets = [a.strip() for a in req.asset.split(',') if a.strip()]
        
        # Validation to prevent duplicate downloads
        for asset in assets:
            info = manager.storage.get_database_info(req.source, asset, "M1")
            if info.get("status") != "Not Found":
                raise HTTPException(status_code=409, detail=f"The database for {asset} via {req.source} already exists on the server. Use the /update request to update the data.")
                
        for asset in assets:
            background_tasks.add_task(manager.download_data, req.source, asset, start_dt, end_dt)
        return {"status": "success", "message": f"Download of {req.asset} via {req.source} started in background"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/update")
def update_data(req: UpdateRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    try:
        assets = [a.strip() for a in req.asset.split(',') if a.strip()]
        for asset in assets:
            background_tasks.add_task(manager.update_data, req.source, asset, req.timeframe)
        return {"status": "success", "message": f"Update of {req.asset} via {req.source} ({req.timeframe}) started in background"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/delete")
def delete_data(req: DeleteRequest, api_key: str = Depends(get_api_key)):
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
def list_databases(api_key: str = Depends(get_api_key)):
    try:
        dbs = manager.list_all()
        return {"databases": dbs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/info/{source}/{asset}/{timeframe}")
def get_info(source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)):
    if not all(re.match(r"^[a-zA-Z0-9_.\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters in URLs")
        
    info = manager.info(source, asset, timeframe)
    if info.get("status") == "Not Found":
        raise HTTPException(status_code=404, detail="Database not found")
    return info
    
@app.get("/search")
def search_assets(source: str = "openbb", query: Optional[str] = None, exchange: Optional[str] = None, api_key: str = Depends(get_api_key)):
    source = source.lower()
    if source == "dukascopy":
        csv_path = Path("metadata") / "dukas_assets.csv"
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
def resample_data(req: ResampleRequest, background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    try:
        background_tasks.add_task(manager.resample_database, req.source, req.asset, req.target_timeframe)
        return {"status": "success", "message": f"Resample of {req.asset} to {req.target_timeframe} started in background"}
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@app.get("/data/{source}/{asset}/{timeframe}")
def get_data_file(source: str, asset: str, timeframe: str, api_key: str = Depends(get_api_key)):
    if not all(re.match(r"^[a-zA-Z0-9_\-]+$", p) for p in [source, asset, timeframe]):
        raise HTTPException(status_code=400, detail="Invalid path parameters")

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
    print("Starting DataManager Network API (Protected) ...")
    uvicorn.run(app, host="0.0.0.0", port=8686)
