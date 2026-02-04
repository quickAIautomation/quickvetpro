import { useState, useEffect } from "react";
import { useAccount } from "./AccountProvider";

const useAccountStatus = () => {
  const [accountStatus, setAccountStatus] = useState(null);
  const { accountId, setAccountId } = useAccount();

  const fetchAccountStatus = async () => {
    if (!accountId) {
      return;
    }

    try {
      const response = await fetch(`/api/account-status?account_id=${accountId}`);
      if (!response.ok) {
        throw new Error("Failed to fetch account status");
      }
      const data = await response.json();
      setAccountStatus(data);
    } catch (error) {
      console.error("Error fetching account status:", error);
      // Não limpar accountId em caso de erro, pois a conta pode existir
    }
  };

  useEffect(() => {
    // Fetch immediately on mount or accountId change
    fetchAccountStatus();

    // Set up interval to fetch every 10 seconds
    const intervalId = setInterval(fetchAccountStatus, 10000);

    // Clean up interval on unmount or when accountId changes
    return () => clearInterval(intervalId);
  }, [accountId]);

  return {
    accountStatus,
    refreshStatus: fetchAccountStatus,
    needsOnboarding: accountStatus?.needsOnboarding ?? true,
  };
};

export default useAccountStatus;