import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './UserList.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

function UserList({ token }) {
  const [users, setUsers] = useState([])
  const [userStats, setUserStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [searchTerm, setSearchTerm] = useState('')

  const axiosInstance = axios.create({
    baseURL: API_BASE,
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })

  useEffect(() => {
    loadUsers()
    loadUserStats()
    const interval = setInterval(() => {
      loadUsers()
      loadUserStats()
    }, 60000) // Atualizar a cada 60s
    return () => clearInterval(interval)
  }, [filter])

  const loadUsers = async () => {
    try {
      const planType = filter === 'all' ? null : filter
      const res = await axiosInstance.get('/admin/users', {
        params: { limit: 200, plan_type: planType }
      })
      setUsers(res.data)
    } catch (err) {
      console.error('Erro ao carregar usuários:', err)
    } finally {
      setLoading(false)
    }
  }

  const loadUserStats = async () => {
    try {
      const res = await axiosInstance.get('/admin/users/stats')
      setUserStats(res.data)
    } catch (err) {
      console.error('Erro ao carregar estatísticas:', err)
    }
  }

  const formatPhone = (phone) => {
    if (!phone) return 'N/A'
    if (phone.length === 13 && phone.startsWith('55')) {
      return `+${phone.slice(0, 2)} (${phone.slice(2, 4)}) ${phone.slice(4, 9)}-${phone.slice(9)}`
    }
    return phone
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A'
    return new Date(dateStr).toLocaleDateString('pt-BR')
  }

  const getPlanLabel = (planType) => {
    const labels = {
      'free': 'Gratuito',
      'monthly': 'Mensal',
      'quarterly': 'Trimestral',
      'semiannual': 'Semestral',
      'annual': 'Anual',
      'enterprise': 'Enterprise',
      'sem_plano': 'Sem Plano'
    }
    return labels[planType] || planType || 'Sem Plano'
  }

  const getPlanColor = (planType) => {
    const colors = {
      'free': '#999',
      'monthly': '#2196f3',
      'quarterly': '#4caf50',
      'semiannual': '#ff9800',
      'annual': '#9c27b0',
      'enterprise': '#f44336',
      'sem_plano': '#ccc'
    }
    return colors[planType] || '#999'
  }

  const filteredUsers = users.filter(user => {
    if (!searchTerm) return true
    const search = searchTerm.toLowerCase()
    return (
      user.phone_number?.toLowerCase().includes(search) ||
      user.email?.toLowerCase().includes(search) ||
      user.name?.toLowerCase().includes(search)
    )
  })

  return (
    <div className="user-list-container">
      <div className="user-list-header">
        <h2>Usuários</h2>
        <div className="user-list-controls">
          <input
            type="text"
            placeholder="Buscar por nome, email ou telefone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="search-input"
          />
          <div className="filter-buttons">
            <button
              className={filter === 'all' ? 'active' : ''}
              onClick={() => setFilter('all')}
            >
              Todos
            </button>
            <button
              className={filter === 'free' ? 'active' : ''}
              onClick={() => setFilter('free')}
            >
              Gratuito
            </button>
            <button
              className={filter === 'monthly' ? 'active' : ''}
              onClick={() => setFilter('monthly')}
            >
              Mensal
            </button>
            <button
              className={filter === 'annual' ? 'active' : ''}
              onClick={() => setFilter('annual')}
            >
              Anual
            </button>
          </div>
        </div>
      </div>

      {userStats && (
        <div className="user-stats-summary">
          <div className="stat-card">
            <div className="stat-value">{userStats.total_users || 0}</div>
            <div className="stat-label">Total de Usuários</div>
          </div>
          {userStats.plan_distribution && Object.entries(userStats.plan_distribution).map(([plan, count]) => (
            <div key={plan} className="stat-card">
              <div className="stat-value" style={{ color: getPlanColor(plan) }}>
                {count}
              </div>
              <div className="stat-label">{getPlanLabel(plan)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="user-list-content">
        {loading ? (
          <div className="loading">Carregando usuários...</div>
        ) : filteredUsers.length === 0 ? (
          <div className="empty">Nenhum usuário encontrado</div>
        ) : (
          <table className="users-table">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Telefone</th>
                <th>Email</th>
                <th>Plano</th>
                <th>Status</th>
                <th>Conversas</th>
                <th>Mensagens</th>
                <th>Mensagens Hoje</th>
                <th>Última Mensagem</th>
                <th>Cadastrado em</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={user.user_id}>
                  <td>{user.name || 'N/A'}</td>
                  <td>{formatPhone(user.phone_number)}</td>
                  <td>{user.email || 'N/A'}</td>
                  <td>
                    <span
                      className="plan-badge"
                      style={{ backgroundColor: getPlanColor(user.plan_type) }}
                    >
                      {getPlanLabel(user.plan_type)}
                    </span>
                  </td>
                  <td>
                    <span className={`status-badge ${user.plan_status === 'active' ? 'active' : 'inactive'}`}>
                      {user.plan_status === 'active' ? 'Ativo' : 'Inativo'}
                    </span>
                  </td>
                  <td>{user.total_conversations || 0}</td>
                  <td><strong>{user.total_messages || 0}</strong></td>
                  <td>{user.messages_today || 0}</td>
                  <td>{user.last_message_at ? formatDate(user.last_message_at) : 'Nunca'}</td>
                  <td>{formatDate(user.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export default UserList
