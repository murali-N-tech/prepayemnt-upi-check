import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createApi, type ApiFetch } from "../lib/api";

interface AuthContextType {
  token: string | null;
  userId: string | null;
  username: string | null;
  login: (token: string, userId: string, username: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
  /** True until the stored session has been read back from localStorage. */
  isLoading: boolean;
  /** fetch wrapper that adds the bearer token and signs out on a 401. */
  api: ApiFetch;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    try {
      const storedToken = localStorage.getItem("token");
      const storedUserId = localStorage.getItem("userId");
      const storedUsername = localStorage.getItem("username");

      if (storedToken && storedUserId && storedUsername) {
        setToken(storedToken);
        setUserId(storedUserId);
        setUsername(storedUsername);
      }
    } catch {
      // localStorage unavailable (private mode, blocked cookies) - start signed out.
    } finally {
      setIsLoading(false);
    }
  }, []);

  const login = useCallback((newToken: string, newUserId: string, newUsername: string) => {
    setToken(newToken);
    setUserId(newUserId);
    setUsername(newUsername);
    try {
      localStorage.setItem("token", newToken);
      localStorage.setItem("userId", newUserId);
      localStorage.setItem("username", newUsername);
    } catch {
      // Session still works for this tab even if it cannot be persisted.
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUserId(null);
    setUsername(null);
    try {
      localStorage.removeItem("token");
      localStorage.removeItem("userId");
      localStorage.removeItem("username");
    } catch {
      // Nothing to clean up.
    }
  }, []);

  const api = useMemo(() => createApi(token, logout), [token, logout]);

  return (
    <AuthContext.Provider
      value={{
        token,
        userId,
        username,
        login,
        logout,
        isAuthenticated: !!token,
        isLoading,
        api,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
