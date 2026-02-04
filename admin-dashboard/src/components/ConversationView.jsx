import React from 'react'
import './ConversationView.css'

function ConversationView({ conversation, onUpdateStatus }) {
  if (!conversation) {
    return (
      <div className="conversation-view empty">
        <div className="empty-message">
          <h3>Selecione uma conversa</h3>
          <p>Escolha uma conversa da lista para visualizar as mensagens</p>
        </div>
      </div>
    )
  }

  const formatPhone = (phone) => {
    if (!phone) return 'N/A'
    if (phone.length === 13 && phone.startsWith('55')) {
      return `+${phone.slice(0, 2)} (${phone.slice(2, 4)}) ${phone.slice(4, 9)}-${phone.slice(9)}`
    }
    return phone
  }

  const formatDateTime = (timestamp) => {
    if (!timestamp) return ''
    const date = new Date(timestamp)
    return date.toLocaleString('pt-BR')
  }

  const handleStatusChange = (e) => {
    const newStatus = e.target.value
    if (onUpdateStatus && newStatus !== conversation.status) {
      onUpdateStatus(conversation.conversation_id, newStatus)
    }
  }

  return (
    <div className="conversation-view">
      <div className="conversation-view-header">
        <div>
          <h3>{formatPhone(conversation.phone_number)}</h3>
          {conversation.user_name && (
            <p className="user-name">{conversation.user_name}</p>
          )}
        </div>
        <div className="status-selector">
          <label>Status:</label>
          <select value={conversation.status} onChange={handleStatusChange}>
            <option value="active">Ativa</option>
            <option value="pending">Pendente</option>
            <option value="resolved">Resolvida</option>
            <option value="inactive">Inativa</option>
          </select>
        </div>
      </div>

      <div className="conversation-info">
        <div className="info-item">
          <span className="info-label">Iniciada em:</span>
          <span>{formatDateTime(conversation.started_at)}</span>
        </div>
        {conversation.resolved_at && (
          <div className="info-item">
            <span className="info-label">Resolvida em:</span>
            <span>{formatDateTime(conversation.resolved_at)}</span>
          </div>
        )}
        <div className="info-item">
          <span className="info-label">Total de mensagens:</span>
          <span>{conversation.total_messages}</span>
        </div>
      </div>

      <div className="messages-container">
        {conversation.messages && conversation.messages.length > 0 ? (
          conversation.messages.map((msg) => (
            <div
              key={msg.message_id}
              className={`message ${msg.role === 'user' ? 'user-message' : 'assistant-message'}`}
            >
              <div className="message-header">
                <span className="message-role">
                  {msg.role === 'user' ? '👤 Usuário' : '🤖 Assistente'}
                </span>
                <span className="message-time">
                  {formatDateTime(msg.created_at)}
                </span>
              </div>
              <div className="message-content">
                {msg.content}
                {msg.has_media && msg.media_type && (
                  <span className="media-badge">
                    📎 {msg.media_type}
                  </span>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="no-messages">
            Carregando mensagens...
          </div>
        )}
      </div>
    </div>
  )
}

export default ConversationView
