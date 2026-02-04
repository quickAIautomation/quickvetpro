import React, { useState, useEffect } from "react";
import { useAccount } from "./AccountProvider";
import useAccountStatus from "./useAccountStatus";
import ConnectOnboarding from "./ConnectOnboarding";
import StorefrontNav from "./StorefrontNav";
import Products from "./Products";

const SuccessDisplay = () => {
  return (
    <div className="success-banner">
      <h2>Assinatura realizada com sucesso</h2>
      <p>Bem-vindo ao QuickVET PRO. Informe seu email abaixo para acessar.</p>
    </div>
  );
};

const ProductForm = ({ onSubmit }) => {
  const [formData, setFormData] = useState({
    productName: "",
    productDescription: "",
    productPrice: 1000,
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(formData);
  };

  const formatPrice = (cents) => {
    return (cents / 100).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  };

  return (
    <form onSubmit={handleSubmit} className="form-group">
      <div className="form-group">
        <label>Nome do Produto/Serviço</label>
        <input
          type="text"
          value={formData.productName}
          onChange={(e) =>
            setFormData({ ...formData, productName: e.target.value })
          }
          placeholder="Ex: Consulta Veterinária"
          required
        />
      </div>
      <div className="form-group">
        <label>Descrição</label>
        <input
          type="text"
          value={formData.productDescription}
          onChange={(e) =>
            setFormData({ ...formData, productDescription: e.target.value })
          }
          placeholder="Ex: Consulta completa com exame físico"
        />
      </div>
      <div className="form-group">
        <label>Preço (em centavos) — {formatPrice(formData.productPrice)}</label>
        <input
          type="number"
          value={formData.productPrice}
          onChange={(e) =>
            setFormData({ ...formData, productPrice: parseInt(e.target.value) })
          }
          min="100"
          required
        />
      </div>
      <button type="submit" className="button">
        Criar Produto
      </button>
    </form>
  );
};

export default function Page() {
  const [showProducts, setShowProducts] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const { accountId } = useAccount();
  const { needsOnboarding } = useAccountStatus();

  // Verificar se voltou do Stripe com sucesso
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    if (query.get("success")) {
      setShowSuccess(true);
      // Limpar URL após mostrar sucesso
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    if (query.get("canceled")) {
      alert("Pagamento cancelado. Você pode tentar novamente quando quiser.");
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const handleCreateProduct = async (formData) => {
    if (!accountId) return;
    if (needsOnboarding) return;

    const response = await fetch("/api/create-product", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...formData, accountId }),
    });

    await response.json();
    setShowForm(false);
  };

  const handleToggleProducts = () => {
    setShowProducts(!showProducts);
  };

  return (
    <div className="container">
      <div className="logo">QuickVET | Dashboard</div>
      
      {/* Banner de sucesso após pagamento */}
      {showSuccess && <SuccessDisplay />}
      
      <ConnectOnboarding />
      
      {!needsOnboarding && accountId && (
        <>
          <button className="button" onClick={() => setShowForm(!showForm)}>
            {showForm ? "Cancelar" : "Adicionar Produto"}
          </button>

          {showForm && (
            <ProductForm accountId={accountId} onSubmit={handleCreateProduct} />
          )}
          <button className="button secondary" onClick={handleToggleProducts}>
            {showProducts ? "Ocultar" : "Ver Produtos"}
          </button>
          {showProducts && (
            <div className="products-section">
              <h3>Seus Produtos</h3>
              <Products />
            </div>
          )}
          <StorefrontNav />
        </>
      )}
    </div>
  );
}
