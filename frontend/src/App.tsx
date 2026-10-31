import React, { useState, useEffect, useCallback } from 'react';
import { Auth } from './components/Auth';
import { Sidebar } from './components/Sidebar';
import { Chat } from './components/Chat';

export const App: React.FC = () => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('access_token'));
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [initializing, setInitializing] = useState<boolean>(() => !!localStorage.getItem('access_token'));

  const handleLogout = useCallback((isExpired = false) => {
    localStorage.removeItem('access_token');
    setToken(null);
    setSelectedDocId(null);
    setInitializing(false);
    if (isExpired) {
      setSessionExpired(true);
    }
  }, []);

  // Read and validate saved auth token on initial load
  useEffect(() => {
    const savedToken = localStorage.getItem('access_token');
    if (savedToken) {
      fetch('http://localhost:8000/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${savedToken}` },
      })
        .then((res) => {
          if (res.ok) {
            setToken(savedToken);
          } else {
            handleLogout(true);
          }
        })
        .catch(() => {
          handleLogout(true);
        })
        .finally(() => {
          setInitializing(false);
        });
    } else {
      setInitializing(false);
    }
  }, [handleLogout]);

  const handleLoginSuccess = (newToken: string) => {
    localStorage.setItem('access_token', newToken);
    setSessionExpired(false);
    setToken(newToken);
    setInitializing(false);
  };

  if (initializing) {
    return (
      <div style={{
        height: '100vh',
        width: '100vw',
        background: '#0f172a',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#f8fafc',
        fontFamily: 'sans-serif'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div className="brand-logo" style={{ margin: '0 auto 16px auto', width: '48px', height: '48px', fontSize: '1.2rem' }}>AI</div>
          <div style={{ fontSize: '0.95rem', color: '#94a3b8' }}>Loading Workspace...</div>
        </div>
      </div>
    );
  }

  if (!token) {
    return (
      <Auth
        onLoginSuccess={handleLoginSuccess}
        sessionExpired={sessionExpired}
      />
    );
  }

  return (
    <div className="app-container">
      <Sidebar
        token={token}
        onLogout={() => handleLogout(false)}
        onUnauthorized={() => handleLogout(true)}
        selectedDocId={selectedDocId}
        onSelectDoc={setSelectedDocId}
      />
      <Chat
        token={token}
        onUnauthorized={() => handleLogout(true)}
        selectedDocId={selectedDocId}
      />
    </div>
  );
};

export default App;
