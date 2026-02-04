"""
API para Navegação Estrutural de Conhecimento
=============================================

Endpoints para o sistema de RAG baseado em navegação hierárquica.
Diferente da busca vetorial, permite rastreabilidade lógica.
"""
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from typing import List, Optional

from app.services.structural_knowledge_service import structural_knowledge_service
from app.infra.cache import KnowledgeCache, CacheMetrics, CACHE_TTL
from app.middleware.auth import require_admin, AuthenticatedUser

logger = logging.getLogger(__name__)
router = APIRouter()


class NavigationQuery(BaseModel):
    query: str
    max_steps: Optional[int] = 5


class NavigationResult(BaseModel):
    query: str
    navigation_path: List[str]
    content: List[dict]
    steps: int


@router.post("/setup")
async def setup_structural_tables(
    user: AuthenticatedUser = Depends(require_admin)
):
    """
    Cria tabelas necessárias para navegação estrutural.
    Requer autenticação de administrador.
    """
    try:
        await structural_knowledge_service.create_tables()
        logger.info(f"Tabelas estruturais criadas por {user.id}")
        return {"status": "success", "message": "Tabelas estruturais criadas"}
    except Exception as e:
        logger.error(f"Erro ao criar tabelas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_structural_stats():
    """Retorna estatísticas da base estrutural"""
    try:
        stats = await structural_knowledge_service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Erro ao obter stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/navigate")
async def navigate_documents(query: NavigationQuery):
    """
    Navega pela estrutura dos documentos para responder uma query.
    
    O sistema lê o sumário, decide qual caminho seguir, e pode fazer
    múltiplos saltos até encontrar a informação necessária.
    
    Diferente da busca vetorial:
    - Segue referências cruzadas (ex: "ver Anexo G")
    - Encontra informações em tabelas e anexos
    - Rastreabilidade do caminho de navegação
    """
    try:
        result = await structural_knowledge_service.navigate(
            query.query, 
            query.max_steps
        )
        return result
    except Exception as e:
        logger.error(f"Erro na navegação: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context")
async def get_structural_context(query: str):
    """
    Retorna contexto estruturado para uma query.
    
    Esta é a função principal para integração com agentes.
    Retorna o contexto formatado com caminho de navegação.
    """
    try:
        context = await structural_knowledge_service.get_context_for_query(query)
        return {
            "query": query,
            "context": context,
            "type": "structural_navigation"
        }
    except Exception as e:
        logger.error(f"Erro ao obter contexto: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def ingest_structural_pdfs(
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_admin)
):
    """
    Inicia processamento estrutural de PDFs em background.
    Requer autenticação de administrador.
    
    Diferente da ingestão vetorial, este processo:
    - Extrai a hierarquia do documento (sumário, capítulos, seções)
    - Preserva referências cruzadas
    - Cria árvore navegável
    """
    logger.info(f"Ingestão estrutural iniciada por {user.id} ({user.type})")
    background_tasks.add_task(
        structural_knowledge_service.ingest_all_pdfs, 
        "knowledge"
    )
    return {
        "status": "Processamento estrutural iniciado em background",
        "info": "Use GET /structural/stats para acompanhar o progresso"
    }


@router.get("/tree/{document_id}")
async def get_document_tree(document_id: int):
    """Retorna a árvore hierárquica completa de um documento"""
    try:
        tree = await structural_knowledge_service.get_document_tree(document_id)
        return tree
    except Exception as e:
        logger.error(f"Erro ao obter árvore: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compare")
async def compare_retrieval_methods(query: str):
    """
    Compara os dois métodos de recuperação para a mesma query.
    
    Útil para demonstrar a diferença entre:
    - Busca vetorial (similaridade semântica)
    - Navegação estrutural (rastreabilidade lógica)
    """
    from app.services.knowledge_service import knowledge_service
    
    try:
        # Busca vetorial
        vector_results = await knowledge_service.search(query, top_k=3)
        
        # Navegação estrutural
        structural_result = await structural_knowledge_service.navigate(query, max_steps=3)
        
        return {
            "query": query,
            "vector_search": {
                "method": "Busca por similaridade semântica (embeddings)",
                "results": [
                    {
                        "content": r["content"][:300] + "...",
                        "similarity": r["similarity"],
                        "file": r["file"]
                    }
                    for r in vector_results
                ]
            },
            "structural_navigation": {
                "method": "Navegação hierárquica (árvore de documentos)",
                "path": structural_result.get("navigation_path", []),
                "results": [
                    {
                        "title": c["title"],
                        "type": c["type"],
                        "page": c["page"],
                        "content": c["content"][:300] + "..."
                    }
                    for c in structural_result.get("content", [])
                ]
            }
        }
    except Exception as e:
        logger.error(f"Erro na comparação: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ENDPOINTS DE CACHE ====================

@router.get("/cache/stats")
async def get_cache_stats():
    """
    Retorna estatísticas do cache Redis.
    
    Mostra hit rate, hits, misses por tipo de cache:
    - vector_search: Busca vetorial
    - structural_navigation: Navegação estrutural
    - context: Contexto formatado
    """
    try:
        stats = await CacheMetrics.get_stats()
        return {
            "cache_stats": stats,
            "ttl_config": CACHE_TTL,
            "info": "Hit rate mais alto = menos custo de inferência"
        }
    except Exception as e:
        logger.error(f"Erro ao obter stats de cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache/invalidate")
async def invalidate_cache(cache_type: Optional[str] = None):
    """
    Invalida o cache.
    
    Args:
        cache_type: Tipo específico (vector_search, structural_navigation, context, toc)
                   Se não especificado, invalida todo o cache.
    """
    try:
        await KnowledgeCache.invalidate(cache_type=cache_type)
        return {
            "status": "success",
            "invalidated": cache_type or "all",
            "message": f"Cache {'de ' + cache_type if cache_type else 'completo'} invalidado"
        }
    except Exception as e:
        logger.error(f"Erro ao invalidar cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))
