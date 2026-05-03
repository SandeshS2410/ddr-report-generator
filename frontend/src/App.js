import React, { useState, useCallback, useRef } from 'react';
import './App.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

// ─── Severity badge colors ────────────────────────────────────────────────────
const severityColor = {
  critical: '#c0392b',
  high: '#e67e22',
  medium: '#f1c40f',
  low: '#27ae60',
};

// ─── Upload Drop Zone ─────────────────────────────────────────────────────────
function DropZone({ label, subLabel, icon, file, onFile, accept }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  }, [onFile]);

  return (
    <div
      className={`drop-zone ${file ? 'has-file' : ''} ${dragging ? 'dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => e.target.files[0] && onFile(e.target.files[0])}
      />
      <div className="drop-icon">{icon}</div>
      <div className="drop-label">{file ? file.name : label}</div>
      <div className="drop-sub">{file ? `${(file.size / 1024).toFixed(1)} KB` : subLabel}</div>
      {file && <div className="drop-check">✓</div>}
    </div>
  );
}

// ─── Report Section ───────────────────────────────────────────────────────────
function ReportSection({ num, title, children }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="report-section">
      <button className="section-header" onClick={() => setOpen(o => !o)}>
        <span className="section-num">{num}</span>
        <span className="section-title">{title}</span>
        <span className="section-toggle">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="section-body">{children}</div>}
    </div>
  );
}

// ─── Parse report text into sections ─────────────────────────────────────────
function parseReport(text) {
  const sections = {};
  const patterns = [
    { key: 'summary', start: '1. PROPERTY ISSUE SUMMARY', end: '2. AREA-WISE OBSERVATIONS' },
    { key: 'observations', start: '2. AREA-WISE OBSERVATIONS', end: '3. PROBABLE ROOT CAUSE' },
    { key: 'rootcause', start: '3. PROBABLE ROOT CAUSE', end: '4. SEVERITY ASSESSMENT' },
    { key: 'severity', start: '4. SEVERITY ASSESSMENT', end: '5. RECOMMENDED ACTIONS' },
    { key: 'actions', start: '5. RECOMMENDED ACTIONS', end: '6. ADDITIONAL NOTES' },
    { key: 'notes', start: '6. ADDITIONAL NOTES', end: '7. MISSING OR UNCLEAR INFORMATION' },
    { key: 'missing', start: '7. MISSING OR UNCLEAR INFORMATION', end: 'END OF REPORT' },
  ];

  for (const { key, start, end } of patterns) {
    const si = text.indexOf(start);
    const ei = text.indexOf(end);
    if (si !== -1) {
      const content = text.slice(si + start.length, ei !== -1 ? ei : undefined).trim();
      sections[key] = content.replace(/^[─\-─]+/gm, '').trim();
    }
  }

  return sections;
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [inspFile, setInspFile] = useState(null);
  const [thermalFile, setThermalFile] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [result, setResult] = useState(null);
  const [rawReport, setRawReport] = useState('');
  const [viewMode, setViewMode] = useState('structured'); // 'structured' | 'raw'
  const [copied, setCopied] = useState(false);
  const [activeImg, setActiveImg] = useState(null);

  const canGenerate = inspFile && thermalFile && apiKey.startsWith('sk-');

  const generate = async () => {
    if (!canGenerate) return;
    setLoading(true);
    setResult(null);
    setRawReport('');
    setStatusMsg('Uploading documents and extracting content…');

    const formData = new FormData();
    formData.append('inspection_report', inspFile);
    formData.append('thermal_report', thermalFile);
    formData.append('api_key', apiKey);

    try {
      setStatusMsg('Analysing documents with Claude AI…');
      const resp = await fetch(`${API_BASE}/generate-ddr`, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${resp.status}`);
      }

      const data = await resp.json();
      setRawReport(data.report);
      setResult(data);
      setStatusMsg('');
    } catch (e) {
      setStatusMsg('ERROR: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const copyReport = () => {
    navigator.clipboard.writeText(rawReport).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const downloadReport = () => {
    const blob = new Blob([rawReport], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `DDR_Report_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
  };

  const sections = result ? parseReport(result.report) : {};

  return (
    <div className="app-root">
      {/* Header */}
      <header className="app-header">
        <div className="header-inner">
          <div className="logo-mark">DDR</div>
          <div>
            <h1 className="app-title">Detailed Diagnostic Report Generator</h1>
            <p className="app-subtitle">AI-powered inspection analysis · Professional inspection analysis & diagnostic reporting</p>
          </div>
        </div>
      </header>

      <main className="main-content">

        {/* Input Panel */}
        <section className="panel input-panel">
          <h2 className="panel-heading">Upload Documents</h2>
          <p className="panel-sub">Supports PDF and image files (JPG, PNG)</p>

          <div className="upload-grid">
            <DropZone
              label="Inspection Report"
              subLabel="Site observations & findings"
              icon="📋"
              file={inspFile}
              onFile={setInspFile}
              accept=".pdf,image/*"
            />
            <DropZone
              label="Thermal Report"
              subLabel="Temperature readings & thermal data"
              icon="🌡️"
              file={thermalFile}
              onFile={setThermalFile}
              accept=".pdf,image/*"
            />
          </div>

          <div className="api-row">
            <label className="api-label">Anthropic API Key</label>
            <input
              className="api-input"
              type="password"
              placeholder="sk-ant-..."
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              autoComplete="off"
            />
          </div>
          <p className="api-hint">Your key is sent directly to Anthropic — never stored on our servers.</p>

          <button
            className={`gen-btn ${loading ? 'loading' : ''}`}
            onClick={generate}
            disabled={!canGenerate || loading}
          >
            {loading ? (
              <><span className="spinner" /> Generating Report…</>
            ) : (
              <><span className="btn-icon">⚡</span> Generate DDR Report</>
            )}
          </button>

          {statusMsg && (
            <div className={`status-msg ${statusMsg.startsWith('ERROR') ? 'error' : 'info'}`}>
              {!statusMsg.startsWith('ERROR') && <span className="spinner small" />}
              {statusMsg}
            </div>
          )}
        </section>

        {/* Result Panel */}
        {result && (
          <section className="panel result-panel">

            {/* Stats bar */}
            <div className="stats-bar">
              <div className="stat-item">
                <span className="stat-val">{result.stats.total_images}</span>
                <span className="stat-label">Images extracted</span>
              </div>
              <div className="stat-item">
                <span className="stat-val">{result.stats.inspection_images}</span>
                <span className="stat-label">From inspection</span>
              </div>
              <div className="stat-item">
                <span className="stat-val">{result.stats.thermal_images}</span>
                <span className="stat-label">From thermal</span>
              </div>
            </div>

            {/* Toolbar */}
            <div className="report-toolbar">
              <div className="view-toggle">
                <button
                  className={viewMode === 'structured' ? 'tog active' : 'tog'}
                  onClick={() => setViewMode('structured')}
                >Structured View</button>
                <button
                  className={viewMode === 'raw' ? 'tog active' : 'tog'}
                  onClick={() => setViewMode('raw')}
                >Raw Text</button>
              </div>
              <div className="toolbar-actions">
                <button className="action-btn" onClick={copyReport}>
                  {copied ? '✓ Copied' : '📋 Copy'}
                </button>
                <button className="action-btn primary" onClick={downloadReport}>
                  ⬇ Download .txt
                </button>
              </div>
            </div>

            {/* Extracted Images Gallery */}
            {result.images && result.images.length > 0 && (
              <div className="images-gallery">
                <h3 className="gallery-heading">Extracted Images ({result.images.length})</h3>
                <div className="img-thumbs">
                  {result.images.map((img) => (
                    <div key={img.id} className="img-thumb" onClick={() => setActiveImg(img)}>
                      <img src={`data:image/jpeg;base64,${img.data}`} alt={img.id} />
                      <div className="img-thumb-label">{img.id}</div>
                      <div className="img-thumb-source">{img.source} · p.{img.page}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Structured view */}
            {viewMode === 'structured' && (
              <div className="structured-report">
                {sections.summary && (
                  <ReportSection num="1" title="Property Issue Summary">
                    <p className="section-text">{sections.summary}</p>
                  </ReportSection>
                )}
                {sections.observations && (
                  <ReportSection num="2" title="Area-wise Observations">
                    <pre className="section-pre">{sections.observations}</pre>
                  </ReportSection>
                )}
                {sections.rootcause && (
                  <ReportSection num="3" title="Probable Root Cause">
                    <pre className="section-pre">{sections.rootcause}</pre>
                  </ReportSection>
                )}
                {sections.severity && (
                  <ReportSection num="4" title="Severity Assessment">
                    <pre className="section-pre">{sections.severity}</pre>
                  </ReportSection>
                )}
                {sections.actions && (
                  <ReportSection num="5" title="Recommended Actions">
                    <pre className="section-pre">{sections.actions}</pre>
                  </ReportSection>
                )}
                {sections.notes && (
                  <ReportSection num="6" title="Additional Notes">
                    <pre className="section-pre">{sections.notes}</pre>
                  </ReportSection>
                )}
                {sections.missing && (
                  <ReportSection num="7" title="Missing or Unclear Information">
                    <pre className="section-pre">{sections.missing}</pre>
                  </ReportSection>
                )}
              </div>
            )}

            {/* Raw view */}
            {viewMode === 'raw' && (
              <pre className="raw-report">{rawReport}</pre>
            )}
          </section>
        )}
      </main>

      {/* Image lightbox */}
      {activeImg && (
        <div className="lightbox" onClick={() => setActiveImg(null)}>
          <div className="lightbox-inner" onClick={e => e.stopPropagation()}>
            <button className="lightbox-close" onClick={() => setActiveImg(null)}>✕</button>
            <img src={`data:image/jpeg;base64,${activeImg.data}`} alt={activeImg.id} />
            <div className="lightbox-meta">
              {activeImg.id} · {activeImg.source} · Page {activeImg.page}
            </div>
          </div>
        </div>
      )}

      <footer className="app-footer">
        <p>DDR Report Generator · Professional Diagnostic Reporting System · For inspection professionals</p>
      </footer>
    </div>
  );
}
