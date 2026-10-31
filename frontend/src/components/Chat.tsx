import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Send, Bot, Sparkles, BookOpen, ShieldCheck, ShieldAlert } from 'lucide-react';
import type { ChatMessage, ChunkMatch, QueryLogResponse } from '../types';

interface ChatProps {
  token: string;
  selectedDocId: string | null;
  onUnauthorized: () => void;
}

export const Chat: React.FC<ChatProps> = ({ token, selectedDocId, onUnauthorized }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputQuestion, setInputQuestion] = useState('');
  const [isStrict, setIsStrict] = useState(false); // False = Normal Search (0.20), True = Strict Search (0.35)
  const [streaming, setStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streaming]);

  // Load chat history from backend on mount or after stream finishes
  const fetchHistory = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch('http://localhost:8000/api/v1/queries', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      if (res.ok) {
        const logs: QueryLogResponse[] = await res.json();
        const historicMessages: ChatMessage[] = [];

        logs.forEach((log) => {
          historicMessages.push({
            id: `${log.id}-q`,
            sender: 'user',
            text: log.question,
            timestamp: new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          });
          if (log.answer) {
            historicMessages.push({
              id: `${log.id}-a`,
              sender: 'assistant',
              text: log.answer,
              timestamp: new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            });
          }
        });

        setMessages(historicMessages);
      }
    } catch (err) {
      console.error('Failed to fetch chat history', err);
    }
  }, [token, onUnauthorized]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Handle SSE streaming answer generation
  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuestion.trim() || streaming) return;

    if (!selectedDocId) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          sender: 'assistant',
          text: '⚠️ Please select a document from the left sidebar before submitting a question.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
      return;
    }

    const userQuestion = inputQuestion.trim();
    setInputQuestion('');

    const userMsgId = Date.now().toString();
    const assistantMsgId = (Date.now() + 1).toString();
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Append user message and placeholder assistant message
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, sender: 'user', text: userQuestion, timestamp: timeStr },
      { id: assistantMsgId, sender: 'assistant', text: '', isStreaming: true, timestamp: timeStr },
    ]);

    setStreaming(true);

    try {
      const response = await fetch('http://localhost:8000/api/v1/queries', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question: userQuestion,
          document_id: selectedDocId,
          strict_search: isStrict,
        }),
      });

      if (response.status === 401) {
        onUnauthorized();
        return;
      }

      if (!response.ok) {
        const errorJson = await response.json();
        throw new Error(errorJson.detail || 'Query request failed');
      }

      if (!response.body) {
        throw new Error('ReadableStream not supported');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let currentSources: ChunkMatch[] = [];
      let accumulatedText = '';
      let currentEvent = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // Keep the last incomplete line in buffer
        buffer = lines.pop() || '';

        for (let i = 0; i < lines.length; i++) {
          let rawLine = lines[i].trim();
          if (!rawLine) continue;

          // Strip any leading 'data: ' wrappers (handles double-wrapped SSE data: event: ... or data: data: ...)
          while (rawLine.startsWith('data: ')) {
            rawLine = rawLine.substring(6).trim();
          }

          if (rawLine.startsWith('event:')) {
            currentEvent = rawLine.replace('event:', '').trim();
          } else if (rawLine.startsWith('data:')) {
            let dataStr = rawLine.replace('data:', '').trim();

            if (currentEvent === 'sources') {
              try {
                currentSources = JSON.parse(dataStr);
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, sources: currentSources }
                      : msg
                  )
                );
              } catch (e) {
                console.error('Failed to parse sources', e);
              }
            } else if (currentEvent === 'delta' || currentEvent === 'message') {
              let tokenText = dataStr;
              if (dataStr.startsWith('"') && dataStr.endsWith('"')) {
                try {
                  tokenText = JSON.parse(dataStr);
                } catch (e) {
                  tokenText = dataStr.slice(1, -1);
                }
              }

              accumulatedText += tokenText;
              const snapshotText = accumulatedText;

              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMsgId
                    ? { ...msg, text: snapshotText, isStreaming: true }
                    : msg
                )
              );
            } else if (currentEvent === 'done') {
              const snapshotText = accumulatedText;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMsgId
                    ? { ...msg, text: snapshotText, isStreaming: false }
                    : msg
                )
              );
            }
          }
        }
      }

      // Final pass after stream closes to ensure message state is updated and loading stops
      const finalText = accumulatedText;
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, text: finalText, isStreaming: false }
            : msg
        )
      );
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                text: `Error: ${err.message || 'Something went wrong.'}`,
                isStreaming: false,
              }
            : msg
        )
      );
    } finally {
      setStreaming(false);
      // Auto-sync finalized message history from backend so UI automatically displays completed answer without needing page refresh!
      await fetchHistory();
    }
  };

  return (
    <div className="chat-container">
      {/* Top Bar / Controls */}
      <div className="chat-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Sparkles size={18} style={{ color: '#a855f7' }} />
          <span className="chat-title">AI Assistant Chat</span>
        </div>

        {/* Strictness Toggle Switch */}
        <div className="toggle-group" title="Select similarity threshold strictness">
          <button
            type="button"
            className={`toggle-btn ${!isStrict ? 'active' : ''}`}
            onClick={() => setIsStrict(false)}
          >
            <ShieldCheck size={13} style={{ display: 'inline', marginRight: '4px', verticalAlign: '-1px' }} />
            Normal Search (0.20)
          </button>
          <button
            type="button"
            className={`toggle-btn ${isStrict ? 'active' : ''}`}
            onClick={() => setIsStrict(true)}
          >
            <ShieldAlert size={13} style={{ display: 'inline', marginRight: '4px', verticalAlign: '-1px' }} />
            Strict Search (0.35)
          </button>
        </div>
      </div>

      {/* Messages Timeline */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div style={{
            margin: 'auto',
            textAlign: 'center',
            maxWidth: '420px',
            padding: '40px 20px',
            color: '#94a3b8'
          }}>
            <Bot size={48} style={{ color: '#6366f1', marginBottom: '16px' }} />
            <h3 style={{ color: '#f8fafc', marginBottom: '8px', fontSize: '1.2rem' }}>What can I help you with today?</h3>
            <p style={{ fontSize: '0.88rem', color: '#64748b' }}>
              Upload your documents from the sidebar, then ask questions about policies, biodata, contracts, or summaries.
            </p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-bubble ${
                msg.sender === 'user' ? 'message-user' : 'message-assistant'
              }`}
            >
              {/* If sources exist, render source citation box */}
              {msg.sources && msg.sources.length > 0 && (
                <div className="sources-container">
                  <div className="sources-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <BookOpen size={13} />
                    <span>Retrieved Sources ({msg.sources.length})</span>
                  </div>
                  {msg.sources.map((src, i) => (
                    <div key={i} className="source-card">
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 600, color: '#e2e8f0' }}>[Source {i + 1}]</span>
                        <span className="source-score">{(src.similarity_score * 100).toFixed(1)}% match</span>
                      </div>
                      <div style={{ fontStyle: 'italic', opacity: 0.9 }}>"{src.content}"</div>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ whiteSpace: 'pre-wrap' }}>
                {msg.text || (msg.isStreaming ? 'Thinking...' : '')}
                {msg.isStreaming && <span style={{ animation: 'pulse 1s infinite' }}> ▋</span>}
              </div>

              <div style={{
                fontSize: '0.7rem',
                opacity: 0.6,
                marginTop: '6px',
                textAlign: msg.sender === 'user' ? 'right' : 'left'
              }}>
                {msg.timestamp}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Form */}
      <div className="chat-input-area">
        {!selectedDocId && (
          <div style={{
            fontSize: '0.82rem',
            color: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: '6px',
            padding: '8px 12px',
            marginBottom: '8px',
            textAlign: 'center'
          }}>
            ⚠️ Please select a document from the left sidebar to start asking questions.
          </div>
        )}
        <form onSubmit={handleSend} className="input-box">
          <input
            type="text"
            className="chat-input"
            placeholder={
              selectedDocId
                ? 'Ask a question about the selected document...'
                : 'Select a document from the sidebar to ask a question...'
            }
            value={inputQuestion}
            onChange={(e) => setInputQuestion(e.target.value)}
            disabled={streaming || !selectedDocId}
          />
          <button
            type="submit"
            className="btn-send"
            disabled={streaming || !inputQuestion.trim() || !selectedDocId}
          >
            <Send size={18} />
          </button>
        </form>
      </div>
    </div>
  );
};
