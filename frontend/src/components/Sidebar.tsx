import React, { useState, useEffect, useRef, useCallback } from 'react';
import { UploadCloud, FileText, Trash2, LogOut, CheckCircle, Clock, AlertTriangle, Filter, X, RotateCw, Eye } from 'lucide-react';
import type { DocumentItem, DocumentListResponse } from '../types';

interface SidebarProps {
  token: string;
  onLogout: () => void;
  onUnauthorized: () => void;
  selectedDocId: string | null;
  onSelectDoc: (id: string | null) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  token,
  onLogout,
  onUnauthorized,
  selectedDocId,
  onSelectDoc,
}) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  // View document content in a new browser tab
  const handleView = (e: React.MouseEvent, docId: string) => {
    e.stopPropagation();
    const url = `http://localhost:8000/api/v1/documents/${docId}/view?token=${token}`;
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  // Fetch document list
  const fetchDocuments = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch('http://localhost:8000/api/v1/documents', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      if (res.ok) {
        const data: DocumentListResponse = await res.json();
        setDocuments(data.items);
      }
    } catch (err) {
      console.error('Failed to fetch documents', err);
    }
  }, [token, onUnauthorized]);

  // Initial fetch on mount or token change (login/page refresh)
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Auto-deselect if the selected document is not ready or gets removed
  useEffect(() => {
    if (selectedDocId) {
      const selectedDoc = documents.find((d) => d.id === selectedDocId);
      if (selectedDoc && selectedDoc.status !== 'ready') {
        onSelectDoc(null);
      }
    }
  }, [documents, selectedDocId, onSelectDoc]);

  // Handle file upload with XHR for real-time progress tracking
  const handleUpload = (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', 'http://localhost:8000/api/v1/documents');
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percent);
      }
    };

    xhr.onload = async () => {
      setUploading(false);
      setUploadProgress(null);
      if (xhr.status === 401) {
        onUnauthorized();
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        await fetchDocuments();
      } else {
        try {
          const errData = JSON.parse(xhr.responseText);
          const detailMsg = typeof errData.detail === 'string'
            ? errData.detail
            : (Array.isArray(errData.detail) && errData.detail.length > 0)
              ? errData.detail.map((i: any) => i.msg || i.message || String(i)).join('; ')
              : (errData.message || 'Upload failed');
          setError(detailMsg.replace(/^Value error,\s*/i, ''));
        } catch {
          setError('Upload failed with status ' + xhr.status);
        }
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      setUploadProgress(null);
      setError('Network error during file upload');
    };

    xhr.send(formData);
  };

  // Handle document deletion
  const handleDelete = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation();
    if (!window.confirm('Are you sure you want to delete this document?')) return;

    try {
      const res = await fetch(`http://localhost:8000/api/v1/documents/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 401) {
        onUnauthorized();
        return;
      }

      if (res.ok) {
        if (selectedDocId === docId) {
          onSelectDoc(null);
        }
        await fetchDocuments();
      }
    } catch (err) {
      console.error('Failed to delete document', err);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'ready':
        return <span className="badge badge-success"><CheckCircle size={12} /> Ready</span>;
      case 'processing':
      case 'pending':
        return <span className="badge badge-warning"><Clock size={12} /> Processing</span>;
      case 'failed':
        return <span className="badge badge-danger"><AlertTriangle size={12} /> Failed</span>;
      default:
        return <span className="badge badge-secondary">{status}</span>;
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  return (
    <aside className="sidebar glass-panel">
      {/* Brand Header */}
      <div className="sidebar-brand">
        <div className="brand-logo">AI</div>
        <div>
          <h2 className="brand-title">Doc Intelligence</h2>
          <p className="brand-subtitle">Multi-Tenant RAG Platform</p>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="alert-error" style={{ marginBottom: '12px', fontSize: '0.78rem' }}>
          {error}
        </div>
      )}

      {/* Dropzone Upload */}
      <div
        className={`upload-zone ${dragActive ? 'dragging' : ''}`}
        onClick={() => !uploading && fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          if (e.dataTransfer.files && e.dataTransfer.files[0] && !uploading) {
            handleUpload(e.dataTransfer.files[0]);
          }
        }}
      >
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: 'none' }}
          accept=".pdf,.txt,.csv,.docx"
          onChange={(e) => {
            if (e.target.files && e.target.files[0] && !uploading) {
              handleUpload(e.target.files[0]);
            }
          }}
        />
        <UploadCloud size={28} style={{ color: '#8b5cf6', marginBottom: '8px' }} />
        <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>
          {uploading
            ? `Uploading... ${uploadProgress !== null ? uploadProgress + '%' : ''}`
            : 'Upload Document'}
        </div>
        <div style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '4px' }}>
          Drag & drop PDF, TXT, CSV, DOCX
        </div>

        {/* Progress Bar */}
        {uploading && uploadProgress !== null && (
          <div style={{
            width: '100%',
            height: '6px',
            background: 'rgba(255, 255, 255, 0.1)',
            borderRadius: '3px',
            marginTop: '10px',
            overflow: 'hidden'
          }}>
            <div style={{
              width: `${uploadProgress}%`,
              height: '100%',
              background: 'linear-gradient(90deg, #8b5cf6, #6366f1)',
              transition: 'width 0.2s ease'
            }} />
          </div>
        )}
      </div>

      {/* Scope Indicator */}
      {selectedDocId && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'rgba(99, 102, 241, 0.15)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          padding: '8px 12px',
          borderRadius: '8px',
          fontSize: '0.78rem'
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#a5b4fc' }}>
            <Filter size={12} /> Scoped to 1 document
          </span>
          <button
            onClick={() => onSelectDoc(null)}
            style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
            title="Clear scope"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Documents List Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: '#64748b' }}>
          Documents ({documents.length})
        </span>
        <button
          onClick={fetchDocuments}
          style={{
            background: 'rgba(255, 255, 255, 0.05)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '4px',
            color: '#94a3b8',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            fontSize: '0.72rem',
            padding: '2px 8px'
          }}
          title="Refresh Documents"
        >
          <RotateCw size={12} /> Refresh
        </button>
      </div>

      <div className="doc-list">
        {documents.length === 0 ? (
          <div style={{ textTransform: 'none', textAlign: 'center', color: '#64748b', fontSize: '0.82rem', padding: '20px 0' }}>
            No documents uploaded yet.
          </div>
        ) : (
          documents.map((doc) => {
            const isSelected = selectedDocId === doc.id;
            const isProcessing = doc.status === 'processing' || doc.status === 'pending';
            return (
              <div
                key={doc.id}
                className="glass-card doc-item"
                style={{
                  borderColor: isSelected ? '#6366f1' : undefined,
                  background: isSelected ? 'rgba(99, 102, 241, 0.12)' : undefined,
                  cursor: 'pointer',
                  flexDirection: 'column',
                  alignItems: 'stretch',
                  gap: '4px'
                }}
                onClick={() => {
                  if (doc.status !== 'ready') return;
                  onSelectDoc(isSelected ? null : doc.id);
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}>
                  <FileText size={20} style={{ color: isSelected ? '#8b5cf6' : '#64748b', flexShrink: 0 }} />
                  <div className="doc-info" style={{ flex: 1, minWidth: 0 }}>
                    <div className="doc-name" title={doc.filename}>{doc.filename}</div>
                    <div className="doc-meta">
                      <span>{formatSize(doc.file_size_bytes)}</span>
                      {doc.chunk_count > 0 && <span>• {doc.chunk_count} chunks</span>}
                    </div>
                  </div>
                  <div style={{ flexShrink: 0 }}>{getStatusBadge(doc.status)}</div>
                  <button
                    className="btn-icon"
                    onClick={(e) => handleView(e, doc.id)}
                    title="View Document"
                    style={{
                      flexShrink: 0,
                      background: 'rgba(99, 102, 241, 0.18)',
                      border: '1px solid rgba(99, 102, 241, 0.35)',
                      color: '#a5b4fc',
                      borderRadius: '4px',
                      padding: '3px 7px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      fontSize: '0.72rem',
                      fontWeight: 500,
                    }}
                  >
                    <Eye size={13} />
                    <span>View</span>
                  </button>
                  <button
                    className="btn-icon-danger"
                    onClick={(e) => handleDelete(e, doc.id)}
                    title="Delete Document"
                    style={{ flexShrink: 0 }}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>

                {isProcessing && (
                  <div style={{ marginTop: '4px', width: '100%' }}>
                    <div style={{ fontSize: '0.68rem', color: '#f59e0b', marginBottom: '4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span>Extracting text & embeddings...</span>
                      <span style={{ color: '#fbbf24', fontWeight: 600 }}>
                        {doc.file_size_bytes < 500 * 1024 ? '~1-2s' : doc.file_size_bytes < 2 * 1024 * 1024 ? '~2-5s' : '~5-10s'}
                      </span>
                    </div>
                    <div style={{
                      width: '100%',
                      height: '4px',
                      background: 'rgba(245, 158, 11, 0.2)',
                      borderRadius: '2px',
                      overflow: 'hidden'
                    }}>
                      <div style={{
                        width: '65%',
                        height: '100%',
                        background: 'linear-gradient(90deg, #f59e0b, #fbbf24)',
                        borderRadius: '2px'
                      }} />
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Logout */}
      <button
        className="btn-secondary"
        onClick={onLogout}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginTop: 'auto' }}
      >
        <LogOut size={16} />
        <span>Sign Out</span>
      </button>
    </aside>
  );
};
