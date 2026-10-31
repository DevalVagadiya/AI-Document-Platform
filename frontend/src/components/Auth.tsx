import React, { useState } from 'react';
import { Lock, Mail, User as UserIcon, ArrowRight, AlertCircle } from 'lucide-react';

interface AuthProps {
  onLoginSuccess: (token: string) => void;
  sessionExpired?: boolean;
}

export const Auth: React.FC<AuthProps> = ({ onLoginSuccess, sessionExpired }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const baseUrl = 'http://localhost:8000/api/v1/auth';
    const endpoint = isLogin ? `${baseUrl}/login` : `${baseUrl}/register`;

    const body = isLogin
      ? { email, password }
      : { email, full_name: fullName, password };

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await response.json();

      if (!response.ok) {
        let msg = 'Authentication failed';
        if (typeof data.detail === 'string') {
          msg = data.detail;
        } else if (Array.isArray(data.detail) && data.detail.length > 0) {
          msg = data.detail.map((item: any) => item.msg || item.message || String(item)).join('; ');
        } else if (data.message) {
          msg = data.message;
        }
        // Clean up Pydantic "Value error, " prefix if present
        msg = msg.replace(/^Value error,\s*/i, '');
        throw new Error(msg);
      }

      if (isLogin) {
        if (data.access_token) {
          onLoginSuccess(data.access_token);
        } else {
          throw new Error('No access token received');
        }
      } else {
        // Automatically switch to login or log in
        setIsLogin(true);
        setError(null);
        alert('Account created successfully! Please log in with your credentials.');
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-wrapper">
      <div className="glass-panel auth-card">
        <div className="brand-logo" style={{ margin: '0 auto 16px auto', width: '48px', height: '48px' }}>
          AI
        </div>
        <h1 className="auth-title">
          {isLogin ? 'Welcome Back' : 'Create Account'}
        </h1>
        <p className="auth-subtitle">
          {isLogin
            ? 'Sign in to access your document intelligence platform'
            : 'Register to start analyzing and querying your documents'}
        </p>

        {sessionExpired && !error && (
          <div className="alert-error" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <AlertCircle size={16} />
            <span>Your session has expired. Please sign in again.</span>
          </div>
        )}

        {error && (
          <div className="alert-error" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="auth-form">
          {!isLogin && (
            <div className="form-group">
              <label>Full Name</label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  required
                  className="form-input"
                  style={{ width: '100%', paddingLeft: '38px' }}
                  placeholder="John Doe"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
                <UserIcon size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
              </div>
            </div>
          )}

          <div className="form-group">
            <label>Email Address</label>
            <div style={{ position: 'relative' }}>
              <input
                type="email"
                required
                className="form-input"
                style={{ width: '100%', paddingLeft: '38px' }}
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Mail size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
            </div>
          </div>

          <div className="form-group">
            <label>Password</label>
            <div style={{ position: 'relative' }}>
              <input
                type="password"
                required
                className="form-input"
                style={{ width: '100%', paddingLeft: '38px' }}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
            </div>
          </div>

          <button type="submit" className="btn-primary" disabled={loading} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginTop: '10px' }}>
            <span>{loading ? 'Processing...' : isLogin ? 'Sign In' : 'Register'}</span>
            {!loading && <ArrowRight size={16} />}
          </button>
        </form>

        <div className="auth-toggle">
          <span>{isLogin ? "Don't have an account?" : 'Already have an account?'}</span>
          <button onClick={() => { setIsLogin(!isLogin); setError(null); }}>
            {isLogin ? 'Register' : 'Sign In'}
          </button>
        </div>
      </div>
    </div>
  );
};
