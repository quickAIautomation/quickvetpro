import React, { useState, useEffect } from 'react'
import axios from 'axios'
import ConversationList from './ConversationList'
import ConversationView from './ConversationView'
import UserList from './UserList'
import StatsBar from './StatsBar'
import './Dashboard.css'

// Detectar ambiente: usar localhost em desenvolvimento, produção em produção
const API_BASE = import.meta.env.VITE_API_BASE || 
  (import.meta.env.DEV ? 'http://localhost:8000' : 'https://quickvetpro.com.br')

function Dashboard({ token, onLogout }) {
  const [stats, setStats] = useState(null)
  const [conversations, setConversations] = useState([])
  const [selectedConversation, setSelectedConversation] = useState(null)
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('conversations') // 'conversations' ou 'users'

  const axiosInstance = axios.create({
    baseURL: API_BASE,
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 30000) // Atualizar a cada 30s
    return () => clearInterval(interval)
  }, [filter])

  const loadData = async () => {
    try {
      // Carregar estatísticas
      const statsRes = await axiosInstance.get('/admin/stats')
      setStats(statsRes.data)

      // Carregar conversas
      const status = filter === 'all' ? null : filter
      const convRes = await axiosInstance.get('/admin/conversations', {
        params: { status, limit: 100 }
      })
      setConversations(convRes.data)

      // Se há conversa selecionada, atualizar
      if (selectedConversation) {
        const updated = convRes.data.find(c => c.conversation_id === selectedConversation.conversation_id)
        if (updated) {
          setSelectedConversation(updated)
        }
      }
    } catch (err) {
      console.error('Erro ao carregar dados:', err)
      if (err.response?.status === 401) {
        onLogout()
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSelectConversation = async (conversation) => {
    setSelectedConversation(conversation)
    
    // Carregar mensagens da conversa
    try {
      const res = await axiosInstance.get(`/admin/conversations/${conversation.conversation_id}/messages`)
      setSelectedConversation({
        ...conversation,
        messages: res.data
      })
    } catch (err) {
      console.error('Erro ao carregar mensagens:', err)
    }
  }

  const handleUpdateStatus = async (conversationId, newStatus) => {
    try {
      await axiosInstance.patch(`/admin/conversations/${conversationId}/status`, {
        status: newStatus
      })
      await loadData()
      if (selectedConversation?.conversation_id === conversationId) {
        setSelectedConversation({
          ...selectedConversation,
          status: newStatus
        })
      }
    } catch (err) {
      console.error('Erro ao atualizar status:', err)
    }
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>QuickVET Admin</h1>
        <button onClick={onLogout} className="logout-button">Sair</button>
      </header>

      {stats && <StatsBar stats={stats} />}

      <div className="dashboard-tabs">
        <button
          className={activeTab === 'conversations' ? 'active' : ''}
          onClick={() => setActiveTab('conversations')}
        >
          Conversas
        </button>
        <button
          className={activeTab === 'users' ? 'active' : ''}
          onClick={() => setActiveTab('users')}
        >
          Usuários
        </button>
      </div>

      <div className="dashboard-content">
        {activeTab === 'conversations' ? (
          <>
            <ConversationList
              conversations={conversations}
              selectedId={selectedConversation?.conversation_id}
              onSelect={handleSelectConversation}
              filter={filter}
              onFilterChange={setFilter}
              loading={loading}
            />
            
            <ConversationView
              conversation={selectedConversation}
              onUpdateStatus={handleUpdateStatus}
            />
          </>
        ) : (
          <UserList token={token} />
        )}
      </div>
    </div>
  )
}

export default Dashboard
