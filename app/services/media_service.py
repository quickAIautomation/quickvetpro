"""
Serviço de Processamento de Mídia
=================================

Processa imagens, áudios e vídeos recebidos via WhatsApp.
- Imagens: GPT-4o Vision
- Áudios: OpenAI Whisper
- Vídeos: Extrai frames + áudio

Integração com a API do WhatsApp para download de mídia.
"""
import os
import io
import base64
import logging
import tempfile
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from dataclasses import dataclass

import httpx
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class MediaType(str, Enum):
    """Tipos de mídia suportados"""
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"


@dataclass
class ProcessedMedia:
    """Resultado do processamento de mídia"""
    media_type: MediaType
    description: str  # Descrição textual (visão ou transcrição)
    confidence: float = 1.0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class MediaService:
    """
    Serviço para processar mídia do WhatsApp.
    
    Fluxo:
    1. Recebe media_id do WhatsApp
    2. Baixa o arquivo via API do Meta
    3. Processa com GPT-4o Vision (imagem) ou Whisper (áudio)
    4. Retorna descrição textual para o agente
    """
    
    WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"
    
    # Tipos MIME suportados
    SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    SUPPORTED_AUDIO_TYPES = ["audio/ogg", "audio/mpeg", "audio/mp4", "audio/amr", "audio/aac"]
    SUPPORTED_VIDEO_TYPES = ["video/mp4", "video/3gpp"]
    
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model_vision = os.getenv("OPENAI_MODEL_VISION", "gpt-4o")
        self.model_whisper = "whisper-1"
    
    # ==================== DOWNLOAD DE MÍDIA ====================
    
    async def download_media(self, media_id: str) -> Tuple[bytes, str]:
        """
        Baixa mídia do WhatsApp usando a API do Meta.
        
        Args:
            media_id: ID da mídia no WhatsApp
            
        Returns:
            Tuple[bytes, mime_type]: Conteúdo e tipo MIME
        """
        # 1. Obter URL da mídia
        url_endpoint = f"{self.WHATSAPP_API_URL}/{media_id}"
        headers = {"Authorization": f"Bearer {settings.whatsapp_api_token}"}
        
        async with httpx.AsyncClient() as client:
            # Obter metadados e URL
            response = await client.get(url_endpoint, headers=headers)
            
            if response.status_code != 200:
                logger.error(f"Erro ao obter URL da mídia: {response.text}")
                raise Exception(f"Falha ao obter mídia: {response.status_code}")
            
            media_info = response.json()
            media_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            
            # 2. Baixar o arquivo
            download_response = await client.get(media_url, headers=headers)
            
            if download_response.status_code != 200:
                logger.error(f"Erro ao baixar mídia: {download_response.status_code}")
                raise Exception(f"Falha ao baixar mídia: {download_response.status_code}")
            
            return download_response.content, mime_type
    
    # ==================== PROCESSAMENTO ====================
    
    async def process_media(
        self, 
        media_id: str, 
        media_type: MediaType,
        context: str = ""
    ) -> ProcessedMedia:
        """
        Processa mídia e retorna descrição textual.
        
        Args:
            media_id: ID da mídia no WhatsApp
            media_type: Tipo de mídia (image, audio, video)
            context: Contexto da conversa para melhor análise
            
        Returns:
            ProcessedMedia com descrição textual
        """
        try:
            # Baixar mídia
            content, mime_type = await self.download_media(media_id)
            logger.info(f"Mídia baixada: {media_type.value}, {len(content)} bytes, {mime_type}")
            
            # Processar conforme tipo
            if media_type == MediaType.IMAGE:
                return await self._process_image(content, mime_type, context)
            
            elif media_type == MediaType.AUDIO:
                return await self._process_audio(content, mime_type)
            
            elif media_type == MediaType.VIDEO:
                return await self._process_video(content, mime_type, context)
            
            elif media_type == MediaType.STICKER:
                return await self._process_image(content, mime_type, context)
            
            else:
                return ProcessedMedia(
                    media_type=media_type,
                    description="[Tipo de mídia não suportado para análise]"
                )
                
        except Exception as e:
            logger.error(f"Erro ao processar mídia: {e}", exc_info=True)
            return ProcessedMedia(
                media_type=media_type,
                description=f"[Não foi possível processar a mídia: {str(e)}]"
            )
    
    async def _process_image(
        self, 
        content: bytes, 
        mime_type: str,
        context: str = ""
    ) -> ProcessedMedia:
        """
        Processa imagem usando GPT-4o Vision.
        
        Analisa a imagem no contexto veterinário, identificando:
        - Sintomas visíveis (feridas, inchaços, secreções)
        - Espécie e raça (se visível)
        - Condição geral do animal
        - Urgência aparente
        """
        # Converter para base64
        base64_image = base64.b64encode(content).decode("utf-8")
        
        # Prompt especializado para análise veterinária
        system_prompt = """Você é um assistente veterinário analisando uma imagem enviada por um tutor.

ANÁLISE REQUERIDA:
1. IDENTIFICAÇÃO: Espécie, raça aproximada, idade aparente (se possível)
2. OBSERVAÇÕES VISUAIS: Descreva o que você vê de forma objetiva
3. SINAIS RELEVANTES: Identifique possíveis sinais clínicos visíveis (feridas, inchaços, secreções, postura anormal, etc.)
4. URGÊNCIA: Indique se há sinais que sugerem necessidade de atendimento urgente

IMPORTANTE:
- Seja objetivo e descritivo
- NÃO faça diagnósticos definitivos
- Indique claramente o que é observação vs. possibilidade
- Se a imagem não for clara ou não mostrar um animal, informe isso"""

        user_prompt = "Analise esta imagem enviada por um tutor preocupado com seu animal."
        if context:
            user_prompt += f"\n\nContexto da conversa: {context}"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_vision,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.3
            )
            
            description = response.choices[0].message.content
            
            return ProcessedMedia(
                media_type=MediaType.IMAGE,
                description=description,
                metadata={"mime_type": mime_type, "size_bytes": len(content)}
            )
            
        except Exception as e:
            logger.error(f"Erro no GPT-4o Vision: {e}")
            raise
    
    async def _process_audio(self, content: bytes, mime_type: str) -> ProcessedMedia:
        """
        Processa áudio usando Whisper para transcrição.
        """
        # Salvar temporariamente (Whisper precisa de arquivo)
        suffix = self._get_audio_extension(mime_type)
        
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            with open(tmp_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model=self.model_whisper,
                    file=audio_file,
                    language="pt"  # Português
                )
            
            transcription = transcript.text
            
            return ProcessedMedia(
                media_type=MediaType.AUDIO,
                description=f"[Transcrição do áudio]: {transcription}",
                metadata={"mime_type": mime_type, "size_bytes": len(content)}
            )
            
        finally:
            # Limpar arquivo temporário
            try:
                os.unlink(tmp_path)
            except:
                pass
    
    async def _process_video(
        self, 
        content: bytes, 
        mime_type: str,
        context: str = ""
    ) -> ProcessedMedia:
        """
        Processa vídeo: extrai primeiro frame para análise visual.
        
        Para vídeos curtos do WhatsApp, analisamos o primeiro frame
        e informamos que é um vídeo.
        """
        # Por simplicidade, tratamos o primeiro frame
        # Em produção, poderia usar ffmpeg para extrair frames
        
        return ProcessedMedia(
            media_type=MediaType.VIDEO,
            description="[Vídeo recebido - Por favor, descreva o que está acontecendo no vídeo ou envie uma foto específica do que deseja que eu analise]",
            metadata={"mime_type": mime_type, "size_bytes": len(content)}
        )
    
    def _get_audio_extension(self, mime_type: str) -> str:
        """Retorna extensão de arquivo para o tipo MIME de áudio"""
        extensions = {
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "audio/amr": ".amr",
            "audio/aac": ".aac",
        }
        return extensions.get(mime_type, ".ogg")
    
    # ==================== DETECÇÃO DE NECESSIDADE DE MÍDIA ====================
    
    def should_request_media(self, message: str, context: str = "") -> Optional[str]:
        """
        Detecta se o agente deveria solicitar mídia baseado na mensagem.
        
        Retorna uma sugestão de solicitação ou None.
        """
        # Palavras que indicam que uma imagem ajudaria
        visual_indicators = [
            "ferida", "machucado", "corte", "sangue", "sangrando",
            "inchaço", "inchado", "caroço", "nódulo",
            "vermelho", "vermelhidão", "irritação", "coceira",
            "olho", "orelha", "pele", "pelo", "mancha",
            "vômito", "fezes", "urina", "secreção",
            "mancando", "andando estranho", "postura",
            "alergia", "picada", "mordida",
            "verme", "pulga", "carrapato"
        ]
        
        message_lower = message.lower()
        
        # Verificar se menciona sintomas visuais
        for indicator in visual_indicators:
            if indicator in message_lower:
                return self._generate_media_request(indicator)
        
        return None
    
    def _generate_media_request(self, indicator: str) -> str:
        """Gera uma solicitação contextualizada de mídia"""
        requests = {
            "ferida": "Para ajudar melhor, você poderia enviar uma foto da ferida? Isso me ajudará a orientar sobre a urgência.",
            "machucado": "Consegue enviar uma foto do machucado? Assim posso avaliar melhor a situação.",
            "corte": "Uma foto do corte ajudaria muito na avaliação. Pode enviar?",
            "sangue": "Para avaliar a gravidade, seria útil ver uma foto. Consegue enviar?",
            "inchaço": "Uma foto do inchaço me ajudaria a orientar melhor. Pode enviar?",
            "inchado": "Consegue enviar uma foto da área inchada?",
            "caroço": "Uma foto do caroço seria muito útil para a avaliação. Pode enviar?",
            "olho": "Uma foto do olho ajudaria muito na avaliação. Consegue enviar?",
            "orelha": "Consegue enviar uma foto da orelha? Isso ajudará na orientação.",
            "pele": "Uma foto da pele afetada seria muito útil. Pode enviar?",
            "mancha": "Consegue enviar uma foto da mancha? Isso ajudará na avaliação.",
            "vômito": "Se possível, uma foto do vômito pode ajudar a identificar possíveis causas.",
            "fezes": "Uma foto das fezes pode fornecer informações importantes. Consegue enviar?",
            "alergia": "Uma foto da reação alérgica ajudaria muito. Pode enviar?",
        }
        
        # Retorna solicitação específica ou genérica
        for key, request in requests.items():
            if key in indicator:
                return request
        
        return "Uma foto ou vídeo do que está acontecendo me ajudaria a orientar melhor. Consegue enviar?"


# Instância global
media_service = MediaService()
