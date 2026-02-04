import React, { useState, useEffect } from "react";
import { useAccount } from "./AccountProvider";

const AccountStatus = () => {
  const { accountId, setAccountId } = useAccount();
  const [accountData, setAccountData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAccountData = async () => {
      if (!accountId) return;
      
      try {
        const response = await fetch(`/api/account/${accountId}`);
        if (response.ok) {
          const data = await response.json();
          setAccountData(data);
        }
      } catch (error) {
        console.error("Erro ao buscar dados da conta:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchAccountData();
  }, [accountId]);

  const handleLogout = () => {
    setAccountId(null);
    localStorage.removeItem("userEmail");
    window.location.reload();
  };

  const handleManageSubscription = async () => {
    try {
      const response = await fetch("/api/create-portal-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId }),
      });
      
      if (response.ok) {
        const data = await response.json();
        window.location.href = data.url;
      }
    } catch (error) {
      console.error("Erro ao abrir portal:", error);
    }
  };

  if (loading) {
    return (
      <div className="account-status">
        <p>Carregando informações da conta...</p>
      </div>
    );
  }

  const planLabels = {
    starter: { name: "Starter", color: "#6366f1" },
    professional: { name: "Professional", color: "#10b981" },
    enterprise: { name: "Enterprise", color: "#8b5cf6" },
    free: { name: "Free", color: "#64748b" },
  };

  const currentPlan = planLabels[accountData?.plan_type] || planLabels.free;
  const isActive = accountData?.plan_status === "active";

  return (
    <div className="account-status">
      <div className="status-header">
        <h3>Assinatura</h3>
        <div 
          className="plan-badge"
          style={{ backgroundColor: currentPlan.color }}
        >
          {currentPlan.name}
        </div>
      </div>

      <div className="status-details">
        <div className="status-item">
          <span>Email</span>
          <span>{accountData?.email || "-"}</span>
        </div>
        <div className="status-item">
          <span>Plano</span>
          <span style={{ color: currentPlan.color }}>
            {currentPlan.name}
          </span>
        </div>
        <div className="status-item">
          <span>Status</span>
          <span className={isActive ? "status-active" : "status-pending"}>
            {isActive ? "Ativo" : "Pendente"}
          </span>
        </div>
      </div>

      <div className="account-actions">
        <button
          onClick={handleManageSubscription}
          className="button"
          disabled={!accountData?.stripe_customer_id}
        >
          Gerenciar Assinatura
        </button>
        <button
          className="button secondary"
          onClick={handleLogout}
        >
          Sair da conta
        </button>
      </div>
    </div>
  );
};

export default AccountStatus;
