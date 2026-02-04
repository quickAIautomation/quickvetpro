"""
Serviço de Formatação de Mensagens WhatsApp
===========================================

Formata mensagens para a API oficial do WhatsApp:
- Divide mensagens longas em partes
- Aplica formatação (negrito, itálico, etc)
- Suporta listas interativas e botões
- Emojis contextuais
"""
import re
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# Limites do WhatsApp
MAX_MESSAGE_LENGTH = 4096
MAX_BUTTON_TEXT = 20
MAX_BUTTONS = 3
MAX_LIST_ITEMS = 10
MAX_LIST_ITEM_TITLE = 24
MAX_LIST_ITEM_DESC = 72


class MessageType(str, Enum):
    """Tipos de mensagem do WhatsApp"""
    TEXT = "text"
    INTERACTIVE_BUTTONS = "interactive_buttons"
    INTERACTIVE_LIST = "interactive_list"


@dataclass
class FormattedMessage:
    """Mensagem formatada para envio"""
    type: MessageType
    content: Any  # Texto ou estrutura interativa
    
    def to_whatsapp_payload(self, to: str) -> dict:
        """Converte para payload da API do WhatsApp"""
        base = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to
        }
        
        if self.type == MessageType.TEXT:
            base["type"] = "text"
            base["text"] = {"preview_url": False, "body": self.content}
            
        elif self.type == MessageType.INTERACTIVE_BUTTONS:
            base["type"] = "interactive"
            base["interactive"] = self.content
            
        elif self.type == MessageType.INTERACTIVE_LIST:
            base["type"] = "interactive"
            base["interactive"] = self.content
        
        return base


@dataclass
class ListItem:
    """Item de uma lista interativa"""
    id: str
    title: str
    description: Optional[str] = None


@dataclass 
class Button:
    """Botão de resposta rápida"""
    id: str
    title: str


class MessageFormatter:
    """
    Formata mensagens para o WhatsApp.
    
    Features:
    - Quebra mensagens longas automaticamente
    - Converte markdown para formatação WhatsApp
    - Adiciona emojis contextuais
    - Cria listas e botões interativos
    """
    
    # Mapeamento de emojis por contexto
    CONTEXT_EMOJIS = {
        "emergência": "🚨",
        "emergencia": "🚨",
        "urgente": "⚠️",
        "atenção": "⚠️",
        "atencao": "⚠️",
        "importante": "❗",
        "dica": "💡",
        "recomendação": "👉",
        "recomendacao": "👉",
        "veterinário": "👨‍⚕️",
        "veterinario": "👨‍⚕️",
        "consulta": "📋",
        "medicamento": "💊",
        "vacina": "💉",
        "alimentação": "🍖",
        "alimentacao": "🍖",
        "água": "💧",
        "agua": "💧",
        "sintoma": "🔍",
        "febre": "🌡️",
        "dor": "😿",
        "vômito": "🤢",
        "vomito": "🤢",
        "diarreia": "💩",
        "ferida": "🩹",
        "olho": "👁️",
        "orelha": "👂",
        "pele": "🐾",
        "cachorro": "🐕",
        "gato": "🐈",
        "cão": "🐕",
        "cao": "🐕",
    }
    
    def format_response(
        self,
        text: str,
        add_emojis: bool = True,
        convert_markdown: bool = True
    ) -> List[FormattedMessage]:
        """
        Formata uma resposta do agente para envio via WhatsApp.
        
        Args:
            text: Texto original da resposta
            add_emojis: Se deve adicionar emojis contextuais
            convert_markdown: Se deve converter markdown para WhatsApp
            
        Returns:
            Lista de mensagens formatadas (pode ser mais de uma se muito longa)
        """
        # Converter markdown para formatação WhatsApp
        if convert_markdown:
            text = self._convert_markdown(text)
        
        # Adicionar emojis contextuais
        if add_emojis:
            text = self._add_context_emojis(text)
        
        # Dividir em partes se necessário
        parts = self._split_message(text)
        
        return [
            FormattedMessage(type=MessageType.TEXT, content=part)
            for part in parts
        ]
    
    def _convert_markdown(self, text: str) -> str:
        """
        Converte markdown comum para formatação do WhatsApp.
        
        WhatsApp suporta:
        - *negrito*
        - _itálico_
        - ~tachado~
        - ```código```
        - > citação (não suportado, convertemos para texto)
        """
        # Headers (## Título) → *TÍTULO*
        text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)
        
        # Bold: **texto** → *texto*
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
        
        # Italic: _texto_ já é suportado
        # __texto__ → _texto_
        text = re.sub(r'__(.+?)__', r'_\1_', text)
        
        # Listas com - ou * → usar emoji
        text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)
        
        # Listas numeradas → manter mas formatar
        text = re.sub(r'^(\d+)\.\s+', r'\1. ', text, flags=re.MULTILINE)
        
        # Citações > texto → remover >
        text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
        
        # Links [texto](url) → texto (url)
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1 (\2)', text)
        
        # Código inline `code` → manter
        # Já suportado pelo WhatsApp
        
        # Bloco de código ```code``` → manter
        # Já suportado pelo WhatsApp
        
        return text
    
    def _add_context_emojis(self, text: str) -> str:
        """Adiciona emojis contextuais baseado nas palavras do texto."""
        # Não adicionar se já tem muitos emojis
        emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
        if emoji_count > 5:
            return text
        
        # Adicionar emoji no início de parágrafos relevantes
        lines = text.split('\n')
        result = []
        
        for line in lines:
            line_lower = line.lower()
            emoji_added = False
            
            # Verificar se a linha começa com palavra-chave
            for keyword, emoji in self.CONTEXT_EMOJIS.items():
                if line_lower.startswith(keyword) or f" {keyword}" in line_lower[:50]:
                    if not any(e in line[:5] for e in self.CONTEXT_EMOJIS.values()):
                        line = f"{emoji} {line}"
                        emoji_added = True
                        break
            
            result.append(line)
        
        return '\n'.join(result)
    
    def _split_message(self, text: str, max_length: int = MAX_MESSAGE_LENGTH) -> List[str]:
        """
        Divide mensagem longa em partes menores.
        
        Tenta quebrar em pontos naturais:
        1. Parágrafos (dupla quebra de linha)
        2. Frases (ponto final)
        3. Vírgulas
        4. Espaços
        """
        if len(text) <= max_length:
            return [text]
        
        parts = []
        remaining = text
        part_num = 1
        
        while remaining:
            if len(remaining) <= max_length:
                parts.append(remaining)
                break
            
            # Encontrar melhor ponto de quebra
            break_point = self._find_break_point(remaining, max_length - 20)  # Margem para indicador
            
            part = remaining[:break_point].strip()
            remaining = remaining[break_point:].strip()
            
            # Adicionar indicador de continuação
            if remaining:
                part += f"\n\n_...continua ({part_num}/{self._estimate_parts(text, max_length)})_"
            
            parts.append(part)
            part_num += 1
        
        return parts
    
    def _find_break_point(self, text: str, max_pos: int) -> int:
        """Encontra o melhor ponto para quebrar o texto."""
        if max_pos >= len(text):
            return len(text)
        
        # Tentar quebrar em parágrafo
        para_break = text.rfind('\n\n', 0, max_pos)
        if para_break > max_pos * 0.5:  # Pelo menos metade do texto
            return para_break + 2
        
        # Tentar quebrar em linha
        line_break = text.rfind('\n', 0, max_pos)
        if line_break > max_pos * 0.5:
            return line_break + 1
        
        # Tentar quebrar em frase
        for punct in ['. ', '! ', '? ']:
            sent_break = text.rfind(punct, 0, max_pos)
            if sent_break > max_pos * 0.3:
                return sent_break + 2
        
        # Tentar quebrar em vírgula
        comma_break = text.rfind(', ', 0, max_pos)
        if comma_break > max_pos * 0.3:
            return comma_break + 2
        
        # Último recurso: quebrar em espaço
        space_break = text.rfind(' ', 0, max_pos)
        if space_break > 0:
            return space_break + 1
        
        # Forçar quebra
        return max_pos
    
    def _estimate_parts(self, text: str, max_length: int) -> int:
        """Estima número de partes que o texto será dividido."""
        return (len(text) // max_length) + 1
    
    # ==================== MENSAGENS INTERATIVAS ====================
    
    def create_button_message(
        self,
        body: str,
        buttons: List[Button],
        header: Optional[str] = None,
        footer: Optional[str] = None
    ) -> FormattedMessage:
        """
        Cria mensagem com botões de resposta rápida.
        
        Args:
            body: Texto principal
            buttons: Lista de botões (máx 3)
            header: Cabeçalho opcional
            footer: Rodapé opcional
        """
        if len(buttons) > MAX_BUTTONS:
            buttons = buttons[:MAX_BUTTONS]
            logger.warning(f"Limitando para {MAX_BUTTONS} botões")
        
        interactive = {
            "type": "button",
            "body": {"text": body[:1024]},  # Limite do body
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn.id,
                            "title": btn.title[:MAX_BUTTON_TEXT]
                        }
                    }
                    for btn in buttons
                ]
            }
        }
        
        if header:
            interactive["header"] = {"type": "text", "text": header[:60]}
        
        if footer:
            interactive["footer"] = {"text": footer[:60]}
        
        return FormattedMessage(
            type=MessageType.INTERACTIVE_BUTTONS,
            content=interactive
        )
    
    def create_list_message(
        self,
        body: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        header: Optional[str] = None,
        footer: Optional[str] = None
    ) -> FormattedMessage:
        """
        Cria mensagem com lista interativa.
        
        Args:
            body: Texto principal
            button_text: Texto do botão que abre a lista
            sections: Lista de seções com items
            header: Cabeçalho opcional
            footer: Rodapé opcional
            
        Exemplo de sections:
        [
            {
                "title": "Opções",
                "rows": [
                    {"id": "opt1", "title": "Opção 1", "description": "Desc 1"},
                    {"id": "opt2", "title": "Opção 2", "description": "Desc 2"}
                ]
            }
        ]
        """
        interactive = {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": button_text[:MAX_BUTTON_TEXT],
                "sections": sections
            }
        }
        
        if header:
            interactive["header"] = {"type": "text", "text": header[:60]}
        
        if footer:
            interactive["footer"] = {"text": footer[:60]}
        
        return FormattedMessage(
            type=MessageType.INTERACTIVE_LIST,
            content=interactive
        )
    
    # ==================== TEMPLATES PRONTOS ====================
    
    def format_emergency_response(self, text: str) -> List[FormattedMessage]:
        """Formata resposta de emergência com destaque."""
        formatted = f"""🚨 *ATENÇÃO - POSSÍVEL EMERGÊNCIA* 🚨

{text}

⚠️ *Procure atendimento veterinário IMEDIATAMENTE!*
"""
        return self.format_response(formatted, add_emojis=False)
    
    def format_with_urgency_buttons(
        self,
        text: str
    ) -> List[FormattedMessage]:
        """
        Formata resposta com botões de nível de urgência.
        Útil para triagem.
        """
        messages = self.format_response(text)
        
        # Adicionar mensagem com botões
        buttons_msg = self.create_button_message(
            body="Baseado na minha orientação, como você classificaria a urgência?",
            buttons=[
                Button(id="urgency_high", title="🔴 Urgente"),
                Button(id="urgency_medium", title="🟡 Pode esperar"),
                Button(id="urgency_low", title="🟢 Tranquilo")
            ],
            footer="Isso nos ajuda a melhorar o atendimento"
        )
        
        messages.append(buttons_msg)
        return messages
    
    def format_with_feedback_buttons(
        self,
        text: str
    ) -> List[FormattedMessage]:
        """Formata resposta com botões de feedback."""
        messages = self.format_response(text)
        
        buttons_msg = self.create_button_message(
            body="Essa resposta foi útil?",
            buttons=[
                Button(id="feedback_yes", title="👍 Sim, ajudou"),
                Button(id="feedback_no", title="👎 Não ajudou"),
                Button(id="feedback_more", title="🤔 Preciso de mais")
            ]
        )
        
        messages.append(buttons_msg)
        return messages
    
    def format_symptom_checklist(
        self,
        intro_text: str,
        symptoms: List[str]
    ) -> List[FormattedMessage]:
        """
        Cria lista interativa de sintomas para o usuário selecionar.
        """
        rows = [
            {
                "id": f"symptom_{i}",
                "title": symptom[:MAX_LIST_ITEM_TITLE],
                "description": f"Selecione se presente"
            }
            for i, symptom in enumerate(symptoms[:MAX_LIST_ITEMS])
        ]
        
        list_msg = self.create_list_message(
            body=intro_text,
            button_text="Ver sintomas",
            sections=[{"title": "Sintomas", "rows": rows}],
            footer="Selecione todos que se aplicam"
        )
        
        return [list_msg]


# Instância global
message_formatter = MessageFormatter()
