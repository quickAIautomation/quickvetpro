"""
Endpoints para Stripe Connect
Gerencia contas conectadas, onboarding e charges
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import logging

from app.services.stripe_service import StripeService
from app.infra.db import get_db_connection
from app.config import settings

router = APIRouter(prefix="/connect", tags=["Stripe Connect"])
logger = logging.getLogger(__name__)

stripe_service = StripeService()


class CreateConnectAccountRequest(BaseModel):
    """Request para criar conta Stripe Connect"""
    account_id: str  # ID da conta na plataforma
    email: str
    country: str = "BR"
    type: str = "express"  # express, standard, custom
    risk_responsibility: str = "stripe"  # platform ou stripe


class CreateAccountLinkRequest(BaseModel):
    """Request para criar Account Link"""
    account_id: str  # ID da conta na plataforma
    return_url: str
    refresh_url: Optional[str] = None


@router.post("/accounts")
async def create_connect_account(request: Request, data: CreateConnectAccountRequest):
    """
    Cria uma conta Stripe Connect para uma conta da plataforma
    
    Args:
        data: Dados da conta conectada
        
    Returns:
        Informações da conta Stripe Connect criada
    """
    try:
        db = await get_db_connection()
        
        # Verificar se a conta existe
        account = await db.fetchrow(
            "SELECT * FROM accounts WHERE account_id = $1",
            data.account_id
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Conta não encontrada")
        
        # Verificar se já existe conta conectada
        existing = await db.fetchrow(
            "SELECT * FROM connected_accounts WHERE account_id = $1",
            data.account_id
        )
        
        if existing:
            # Retornar conta existente
            stripe_account = stripe_service.get_connect_account(existing['stripe_account_id'])
            return JSONResponse({
                "account_id": data.account_id,
                "stripe_account_id": existing['stripe_account_id'],
                "charges_enabled": existing['charges_enabled'],
                "payouts_enabled": existing['payouts_enabled'],
                "onboarding_status": existing['onboarding_status'],
                "already_exists": True
            })
        
        # Criar conta Stripe Connect
        capabilities = {
            'card_payments': {'requested': True},
            'transfers': {'requested': True}
        }
        
        metadata = {
            'account_id': data.account_id,
            'email': data.email
        }
        
        stripe_account = stripe_service.create_connect_account(
            email=data.email,
            country=data.country,
            type=data.type,
            capabilities=capabilities,
            metadata=metadata
        )
        
        # Salvar no banco
        await db.execute("""
            INSERT INTO connected_accounts (
                account_id, stripe_account_id, charges_enabled, payouts_enabled,
                onboarding_status, risk_responsibility, account_type, country
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            data.account_id,
            stripe_account.id,
            stripe_account.charges_enabled,
            stripe_account.payouts_enabled,
            'pending',
            data.risk_responsibility,
            data.type,
            data.country
        )
        
        logger.info(f"Conta Stripe Connect criada: {stripe_account.id} para account {data.account_id}")
        
        return JSONResponse({
            "account_id": data.account_id,
            "stripe_account_id": stripe_account.id,
            "charges_enabled": stripe_account.charges_enabled,
            "payouts_enabled": stripe_account.payouts_enabled,
            "onboarding_status": "pending",
            "already_exists": False
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar conta Stripe Connect: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar conta conectada")


@router.post("/accounts/{account_id}/onboard")
async def create_account_link(
    request: Request,
    account_id: str,
    data: CreateAccountLinkRequest
):
    """
    Cria Account Link para onboarding de conta conectada
    
    Args:
        account_id: ID da conta na plataforma
        data: Dados do Account Link
        
    Returns:
        URL do Account Link para redirecionamento
    """
    try:
        db = await get_db_connection()
        
        # Buscar conta conectada
        connected_account = await db.fetchrow(
            "SELECT * FROM connected_accounts WHERE account_id = $1",
            account_id
        )
        
        if not connected_account:
            raise HTTPException(status_code=404, detail="Conta conectada não encontrada")
        
        # Determinar URLs
        base_url = str(request.base_url).rstrip('/')
        refresh_url = data.refresh_url or f"{base_url}/connect/accounts/{account_id}/onboard/refresh"
        return_url = data.return_url or f"{base_url}/connect/accounts/{account_id}/onboard/return"
        
        # Criar Account Link
        account_link = stripe_service.create_account_link(
            account_id=connected_account['stripe_account_id'],
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding"
        )
        
        logger.info(f"Account Link criado para conta {account_id}")
        
        return JSONResponse({
            "url": account_link.url,
            "expires_at": account_link.expires_at
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar Account Link: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar Account Link")


@router.get("/accounts/{account_id}/status")
async def get_connect_account_status(account_id: str):
    """
    Retorna status da conta Stripe Connect
    
    Args:
        account_id: ID da conta na plataforma
        
    Returns:
        Status da conta conectada
    """
    try:
        db = await get_db_connection()
        
        # Buscar conta conectada
        connected_account = await db.fetchrow(
            "SELECT * FROM connected_accounts WHERE account_id = $1",
            account_id
        )
        
        if not connected_account:
            raise HTTPException(status_code=404, detail="Conta conectada não encontrada")
        
        # Buscar informações atualizadas do Stripe
        try:
            stripe_account = stripe_service.get_connect_account(connected_account['stripe_account_id'])
            
            # Atualizar no banco se necessário
            if (stripe_account.charges_enabled != connected_account['charges_enabled'] or
                stripe_account.payouts_enabled != connected_account['payouts_enabled']):
                
                onboarding_status = 'pending'
                if stripe_account.charges_enabled and stripe_account.payouts_enabled:
                    onboarding_status = 'complete'
                elif stripe_account.details_submitted:
                    onboarding_status = 'in_progress'
                
                await db.execute("""
                    UPDATE connected_accounts
                    SET charges_enabled = $1,
                        payouts_enabled = $2,
                        onboarding_status = $3,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = $4
                """,
                    stripe_account.charges_enabled,
                    stripe_account.payouts_enabled,
                    onboarding_status,
                    account_id
                )
        except Exception as e:
            logger.warning(f"Erro ao buscar status do Stripe: {e}, usando dados do banco")
            stripe_account = None
        
        return JSONResponse({
            "account_id": account_id,
            "stripe_account_id": connected_account['stripe_account_id'],
            "charges_enabled": connected_account['charges_enabled'],
            "payouts_enabled": connected_account['payouts_enabled'],
            "onboarding_status": connected_account['onboarding_status'],
            "risk_responsibility": connected_account['risk_responsibility'],
            "account_type": connected_account['account_type']
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao buscar status da conta: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar status")


@router.get("/accounts/{account_id}/dashboard")
async def get_dashboard_link(account_id: str):
    """
    Retorna link para Express Dashboard da conta conectada
    
    Args:
        account_id: ID da conta na plataforma
        
    Returns:
        URL do dashboard
    """
    try:
        db = await get_db_connection()
        
        # Buscar conta conectada
        connected_account = await db.fetchrow(
            "SELECT * FROM connected_accounts WHERE account_id = $1",
            account_id
        )
        
        if not connected_account:
            raise HTTPException(status_code=404, detail="Conta conectada não encontrada")
        
        # Criar login link
        login_link = stripe_service.create_login_link(connected_account['stripe_account_id'])
        
        return JSONResponse({
            "url": login_link.url
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao criar login link: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar login link")


@router.get("/accounts")
async def list_connect_accounts():
    """
    Lista todas as contas Stripe Connect
    
    Returns:
        Lista de contas conectadas
    """
    try:
        db = await get_db_connection()
        
        accounts = await db.fetch("""
            SELECT 
                ca.account_id,
                ca.stripe_account_id,
                ca.charges_enabled,
                ca.payouts_enabled,
                ca.onboarding_status,
                ca.risk_responsibility,
                ca.account_type,
                a.email,
                a.clinic_name
            FROM connected_accounts ca
            JOIN accounts a ON ca.account_id = a.account_id
            ORDER BY ca.created_at DESC
        """)
        
        return JSONResponse({
            "accounts": [
                {
                    "account_id": acc['account_id'],
                    "stripe_account_id": acc['stripe_account_id'],
                    "email": acc['email'],
                    "clinic_name": acc['clinic_name'],
                    "charges_enabled": acc['charges_enabled'],
                    "payouts_enabled": acc['payouts_enabled'],
                    "onboarding_status": acc['onboarding_status'],
                    "risk_responsibility": acc['risk_responsibility'],
                    "account_type": acc['account_type']
                }
                for acc in accounts
            ]
        })
        
    except Exception as e:
        logger.error(f"Erro ao listar contas conectadas: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar contas")
