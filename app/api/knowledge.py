"""
API para gerenciar a base de conhecimento veterinario
"""
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.services.knowledge_service import knowledge_service
from app.middleware.auth import require_admin, AuthenticatedUser

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchQuery(BaseModel):
    query: str
    top_k: Optional[int] = 5


class SearchResult(BaseModel):
    content: str
    file: str
    chunk: int
    similarity: float


@router.get("/stats")
async def get_knowledge_stats():
    """Retorna estatisticas da base de conhecimento"""
    try:
        stats = await knowledge_service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Erro ao obter stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=List[SearchResult])
async def search_knowledge(query: SearchQuery):
    """Busca na base de conhecimento"""
    try:
        results = await knowledge_service.search(query.query, query.top_k)
        return results
    except Exception as e:
        logger.error(f"Erro na busca: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest_pdfs(
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_admin)
):
    """
    Inicia ingestao de PDFs em background.
    Requer autenticação de administrador.
    """
    background_tasks.add_task(knowledge_service.ingest_all_pdfs, "knowledge")
    logger.info(f"Ingestão iniciada por {user.id} ({user.type})")
    return {"status": "Ingestao iniciada em background"}


@router.get("/context")
async def get_context(query: str, max_tokens: int = 2000):
    """Retorna contexto formatado para uma query (debug)"""
    try:
        context = await knowledge_service.get_context_for_query(query, max_tokens)
        return {
            "query": query,
            "context": context,
            "tokens_aprox": len(context.split()) * 1.3
        }
    except Exception as e:
        logger.error(f"Erro ao obter contexto: {e}")
        raise HTTPException(status_code=500, detail=str(e))
