import React, { useState, useEffect } from "react";
import { useAccount } from "./AccountProvider";
import useAccountStatus from "./useAccountStatus";

const Product = ({ name, description, price, priceId, image }) => {
  const { accountId } = useAccount();

  const formatPrice = (cents) => {
    return (cents / 100).toLocaleString("pt-BR", {
      style: "currency",
      currency: "BRL",
    });
  };

  return (
    <div className="product round-border">
      <div className="product-info">
        <img src={image} alt={name} />
        <div className="description">
          <h3>{name}</h3>
          <h5>{formatPrice(price)}</h5>
          {description && (
            <p style={{ fontSize: "0.8rem", marginTop: "0.25rem" }}>
              {description}
            </p>
          )}
        </div>
      </div>

      <form action="/api/create-checkout-session" method="POST">
        <input type="hidden" name="priceId" value={priceId} />
        <input type="hidden" name="accountId" value={accountId} />
        <button className="button" type="submit">
          Contratar
        </button>
      </form>
    </div>
  );
};

const Products = () => {
  const { accountId } = useAccount();
  const { needsOnboarding } = useAccountStatus();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchProducts = async () => {
    if (!accountId) return;
    if (needsOnboarding) return;

    try {
      const response = await fetch(`/api/products/${accountId}`);
      if (response.ok) {
        const data = await response.json();
        setProducts(data);
      }
    } catch (error) {
      console.error("Erro ao buscar produtos:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
    const intervalId = setInterval(fetchProducts, 5000);
    return () => clearInterval(intervalId);
  }, [accountId, needsOnboarding]);

  if (loading) {
    return <p>Carregando produtos...</p>;
  }

  if (products.length === 0) {
    return (
      <p style={{ textAlign: "center", color: "var(--text-secondary)" }}>
        Nenhum produto cadastrado ainda. Clique em "Adicionar Produto/Serviço"
        para criar seu primeiro produto.
      </p>
    );
  }

  return (
    <div>
      {products.map((product) => (
        <Product key={product.id} {...product} />
      ))}
    </div>
  );
};

export default Products;
