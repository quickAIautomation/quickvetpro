import React, { useState, useEffect } from 'react';
import './App.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// Planos padrão (fallback se não conseguir buscar do Stripe)
const DEFAULT_PLANS = [
  {
    id: 'starter',
    name: 'Starter',
    price: 'R$ 49,90',
    period: '/mês',
    description: 'Ideal para clínicas pequenas',
    features: [
      '50 mensagens/dia',
      'Suporte por email',
      '1 usuário',
      'Relatórios básicos'
    ],
    lookupKey: 'starter_plan',
    popular: false,
    color: '#6366f1'
  },
  {
    id: 'professional',
    name: 'Professional',
    price: 'R$ 99,90',
    period: '/mês',
    description: 'Para clínicas em crescimento',
    features: [
      '200 mensagens/dia',
      'Suporte prioritário',
      '5 usuários',
      'Relatórios avançados',
      'Integrações'
    ],
    lookupKey: 'professional_plan',
    popular: true,
    color: '#10b981'
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: 'R$ 199,90',
    period: '/mês',
    description: 'Para grandes operações',
    features: [
      'Mensagens ilimitadas',
      'Suporte 24/7',
      'Usuários ilimitados',
      'Dashboard personalizado',
      'API dedicada',
      'SLA garantido'
    ],
    lookupKey: 'enterprise_plan',
    popular: false,
    color: '#8b5cf6'
  }
];

const PlanCard = ({ plan }) => (
  <div className={`plan-card ${plan.popular ? 'popular' : ''}`}>
    {plan.popular && <div className="popular-badge">Recomendado</div>}
    <div className="plan-header">
      <h3 className="plan-name">{plan.name}</h3>
      <p className="plan-description">{plan.description}</p>
      <div className="plan-price">
        <span className="price">{plan.price}</span>
        <span className="period">{plan.period}</span>
      </div>
    </div>
    <div className="plan-features">
      <ul>
        {plan.features.map((feature, index) => (
          <li key={index}>
            <CheckIcon color={plan.color} />
            {feature}
          </li>
        ))}
      </ul>
    </div>
    <form action={`${API_BASE}/api/stripe/create-checkout-session`} method="POST">
      {plan.lookupKey && (
        <input type="hidden" name="lookup_key" value={plan.lookupKey} />
      )}
      {plan.priceId && !plan.lookupKey && (
        <input type="hidden" name="price_id" value={plan.priceId} />
      )}
      <button 
        type="submit" 
        className="checkout-button"
        style={{ backgroundColor: plan.color }}
      >
        Assinar {plan.name}
      </button>
    </form>
  </div>
);

const ProductDisplay = ({ plans, loading }) => {
  if (loading) {
    return (
      <div className="pricing-container">
        <div className="pricing-header">
          <div className="logo-mark">Q</div>
          <h1>QuickVET PRO</h1>
          <p className="tagline">Carregando planos...</p>
        </div>
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <p>Buscando planos disponíveis...</p>
        </div>
      </div>
    );
  }

  if (!plans || plans.length === 0) {
    return (
      <div className="pricing-container">
        <div className="pricing-header">
          <div className="logo-mark">Q</div>
          <h1>QuickVET PRO</h1>
          <p className="tagline">Nenhum plano disponível no momento</p>
        </div>
        <div style={{ textAlign: 'center', padding: '2rem' }}>
          <p>Entre em contato para mais informações.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="pricing-container">
      <div className="pricing-header">
        <div className="logo-mark">Q</div>
        <h1>QuickVET PRO</h1>
        <p className="tagline">Escolha o plano ideal para sua clínica</p>
      </div>
      <div className="plans-grid">
        {plans.map((plan) => (
          <PlanCard key={plan.id || plan.lookupKey} plan={plan} />
        ))}
      </div>
    </div>
  );
};

const SuccessDisplay = ({ sessionId }) => {
  return (
    <div className="success-container">
      <div className="success-card">
        <div className="success-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <h2>Assinatura confirmada</h2>
        <p>Obrigado por assinar o QuickVET PRO</p>
        <p className="redirect-info">Redirecionando para o Dashboard...</p>
        <div className="button-group">
          <a href="http://localhost:3000/" className="dashboard-button">
            Acessar Dashboard
          </a>
          <form action={`${API_BASE}/api/stripe/create-portal-session`} method="POST">
            <input type="hidden" name="session_id" value={sessionId} />
            <button type="submit" className="manage-button">
              Gerenciar assinatura
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

const Message = ({ message }) => (
  <div className="message-container">
    <div className="message-card">
      <p>{message}</p>
      <a href="/" className="back-link">Voltar aos planos</a>
    </div>
  </div>
);

export default function App() {
  const [message, setMessage] = useState('');
  const [success, setSuccess] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);

  // Buscar planos do Stripe
  useEffect(() => {
    const fetchPlans = async () => {
      try {
        console.log('Buscando planos do Stripe em:', `${API_BASE}/api/stripe/products?active_only=true`);
        const response = await fetch(`${API_BASE}/api/stripe/products?active_only=true`);
        
        console.log('Status da resposta:', response.status, response.statusText);
        
        if (response.ok) {
          const data = await response.json();
          const stripePlans = data.products || [];
          
          console.log('Produtos recebidos do Stripe:', stripePlans);
          console.log('Número de produtos:', stripePlans.length);
          
          if (stripePlans.length === 0) {
            console.warn('Nenhum produto encontrado no Stripe. Usando planos padrão.');
            setPlans(DEFAULT_PLANS);
            setLoading(false);
            return;
          }
          
          // Converter produtos do Stripe para formato de planos
          const formattedPlans = stripePlans.flatMap(product => {
            console.log('Processando produto:', product.name, 'Preços:', product.prices?.length || 0);
            
            if (!product.prices || product.prices.length === 0) {
              console.warn(`Produto ${product.name} não tem preços`);
              return [];
            }
            
            const validPrices = product.prices.filter(price => {
              const hasRecurring = price && price.recurring;
              const isActive = price && price.active;
              console.log(`Preço ${price.id}: active=${isActive}, recurring=${!!hasRecurring}`);
              return isActive && hasRecurring;
            });
            
            console.log(`Produto ${product.name}: ${validPrices.length} preços válidos de ${product.prices.length} totais`);
            
            return validPrices.map(price => {
              const amount = (price.unit_amount || 0) / 100; // Converter centavos para reais
              const interval = price.recurring?.interval || 'month';
              const intervalCount = price.recurring?.interval_count || 1;
              
              // Determinar período
              let period = '/mês';
              if (interval === 'year') {
                period = '/ano';
              } else if (interval === 'month' && intervalCount === 3) {
                period = '/trimestre';
              } else if (interval === 'month' && intervalCount === 6) {
                period = '/semestre';
              }
              
              // Extrair features do metadata (não usar description)
              const metadata = product.metadata || {};
              let features = [];
              
              // Se tiver features no metadata, usar elas
              if (metadata.features) {
                features = metadata.features.split(',').map(f => f.trim()).filter(f => f.length > 0);
              }
              
              // Se não tiver features no metadata, criar features padrão baseadas no nome do plano
              if (features.length === 0) {
                const planName = product.name.toLowerCase();
                if (planName.includes('starter')) {
                  features = [
                    '50 mensagens/dia',
                    'Suporte por email',
                    '1 usuário',
                    'Relatórios básicos'
                  ];
                } else if (planName.includes('business')) {
                  features = [
                    '200 mensagens/dia',
                    'Suporte prioritário',
                    '5 usuários',
                    'Relatórios avançados',
                    'Integrações'
                  ];
                } else if (planName.includes('pro')) {
                  features = [
                    '500 mensagens/dia',
                    'Suporte 24/7',
                    'Usuários ilimitados',
                    'Relatórios completos',
                    'API dedicada',
                    'Prioridade máxima'
                  ];
                } else if (planName.includes('elite')) {
                  features = [
                    'Mensagens ilimitadas',
                    'Suporte 24/7',
                    'Usuários ilimitados',
                    'Dashboard personalizado',
                    'API dedicada',
                    'SLA garantido',
                    'Economia anual'
                  ];
                } else {
                  features = ['Plano ativo no Stripe'];
                }
              }
              
              return {
                id: product.id,
                name: product.name,
                price: `R$ ${amount.toFixed(2).replace('.', ',')}`,
                period: period,
                description: product.description || metadata.description || '',
                features: features,
                lookupKey: price.lookup_key || price.id,
                priceId: price.id,
                popular: metadata.popular === 'true' || false,
                color: metadata.color || '#6366f1'
              };
            });
          });
          
          console.log('Planos formatados:', formattedPlans.length);
          
          if (formattedPlans.length > 0) {
            // Ordenar planos do mais barato para o mais caro (pelo valor total do plano)
            const sortedPlans = formattedPlans.sort((a, b) => {
              // Extrair valor numérico do preço (remover "R$ " e substituir "," por ".")
              const priceA = parseFloat(a.price.replace('R$ ', '').replace(',', '.'));
              const priceB = parseFloat(b.price.replace('R$ ', '').replace(',', '.'));
              
              // Ordenar pelo valor total do plano (não mensal)
              return priceA - priceB;
            });
            
            console.log('Usando planos do Stripe (ordenados):', sortedPlans);
            setPlans(sortedPlans);
          } else {
            console.warn('Nenhum plano válido encontrado (produtos sem preços recorrentes ativos). Usando planos padrão.');
            setPlans(DEFAULT_PLANS);
          }
        } else {
          const errorText = await response.text();
          console.error('Erro na resposta da API:', response.status, errorText);
          console.warn('Usando planos padrão devido a erro na API');
          setPlans(DEFAULT_PLANS);
        }
      } catch (error) {
        console.error('Erro ao buscar planos:', error);
        console.warn('Usando planos padrão devido a erro na requisição');
        setPlans(DEFAULT_PLANS);
      } finally {
        setLoading(false);
      }
    };

    fetchPlans();
  }, []);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);

    if (query.get('success')) {
      setSuccess(true);
      setSessionId(query.get('session_id'));
    }

    if (query.get('canceled')) {
      setSuccess(false);
      setMessage("Pedido cancelado. Volte quando estiver pronto.");
    }
  }, [sessionId]);

  if (!success && message === '') {
    return <ProductDisplay plans={plans} loading={loading} />;
  } else if (success && sessionId !== '') {
    return <SuccessDisplay sessionId={sessionId} />;
  } else {
    return <Message message={message} />;
  }
}

const CheckIcon = ({ color }) => (
  <svg className="check-icon" viewBox="0 0 24 24" fill={color}>
    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
  </svg>
);
