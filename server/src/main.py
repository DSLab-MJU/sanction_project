import psycopg
from fastapi import Depends, FastAPI, HTTPException

from src.db import get_db
from src.dtos import SearchRequest, SearchResponse
from src.sanction.service import search_sanctions

app = FastAPI(
    title="Sanctions Search API",
    version="1.0.0",
    description="Invoice 기반 제재 대상 식별 API",
)

@app.get(
    "/health",
    summary="Health check",
)
def health(conn: psycopg.Connection = Depends(get_db)) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"status": "ok"}

@app.post(
    "/search",
    response_model=SearchResponse,
    summary="Search sanctions candidates",
    description="Invoice에서 추출된 정보를 기반으로 DB에서 후보를 검색",
)
def search(
    req: SearchRequest,
    conn: psycopg.Connection = Depends(get_db),
) -> SearchResponse:
    try:
        candidates = search_sanctions(conn, req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"search failed: {e}") from e

    return SearchResponse(
        invoice_number=req.invoice_number,
        party_count=len(req.parties),
        hit_count=len(candidates),
        candidates=candidates,
    )