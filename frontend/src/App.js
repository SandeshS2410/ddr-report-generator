import React, { useState, useCallback, useRef } from 'react';
import './App.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

// ─── Image helpers ────────────────────────────────────────────────────────────

function buildImageMap(images) {
  const map = {};
  if (images) images.forEach(img => { map[img.id] = img; });
  return map;
}

function typeBadgeColor(imgType) {
  if (imgType === 'thermal_scan')     return '#e65c00';
  if (imgType === 'visual_photo')     return '#1a7a5e';
  if (imgType === 'inspection_photo') return '#3b6fd4';
  return '#888';
}

function typeLabel(imgType) {
  if (imgType === 'thermal_scan')     return '🌡 Thermal Scan';
  if (imgType === 'visual_photo')     return '📷 Visual Photo';
  if (imgType === 'inspection_photo') return '🔍 Inspection Photo';
  return imgType || 'Image';
}

// ─── Drop Zone ────────────────────────────────────────────────────────────────

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

// ─── Collapsible Section ──────────────────────────────────────────────────────

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

// ─── Report text renderer with inline images ──────────────────────────────────
/**
 * Splits report text on {IMAGE:id} tokens.
 * Each token is replaced with the actual image from imageMap.
 * Plain text is rendered with basic markdown formatting.
 */
function ReportWithImages({ text, imageMap, onImageClick }) {
  if (!text) return null;

  // Split on {IMAGE:some_id} — this is the token format the backend/AI uses
  const parts = text.split(/(\{IMAGE:[^}]+\})/g);

  return (
    <div className="section-content">
      {parts.map((part, i) => {
        // Check if this part is an image token
        const match = part.match(/^\{IMAGE:([^}]+)\}$/);
        if (match) {
          const imgId = match[1].trim();
          const img   = imageMap[imgId];

          if (img) {
            // Render the actual image
            return (
              <div key={i} className="inline-image-wrap">
                <img
                  src={`data:${img.mime_type};base64,${img.data}`}
                  alt={imgId}
                  className="inline-report-img"
                  onClick={() => onImageClick && onImageClick(img)}
                  title="Click to enlarge"
                />
                <div className="inline-img-caption">
                  <span
                    className="img-badge"
                    style={{ backgroundColor: typeBadgeColor(img.img_type) }}
                  >
                    {typeLabel(img.img_type)}
                  </span>
                  <span className="img-badge-meta">
                    {img.source} · Page {img.page} · {img.size_kb} KB
                  </span>
                </div>
              </div>
            );
          }

          // Image ID referenced but not found
          return (
            <div key={i} className="img-not-found">
              ⚠ Image Not Available: <code>{imgId}</code>
            </div>
          );
        }

        // Render plain text with basic markdown
        return <MarkdownText key={i} text={part} />;
      })}
    </div>
  );
}

/** Renders basic markdown: ##, ###, **, - bullets, table rows */
function MarkdownText({ text }) {
  if (!text) return null;
  const lines = text.split('\n');

  return (
    <>
      {lines.map((line, i) => {
        if (line.startsWith('### '))
          return <h4 key={i} className="md-h3">{line.slice(4)}</h4>;
        if (line.startsWith('## '))
          return <h3 key={i} className="md-h2">{line.slice(3)}</h3>;
        if (line.startsWith('|'))
          return <div key={i} className="md-table-row">{line}</div>;
        if ((line.startsWith('**') && line.endsWith('**')) && line.length > 4)
          return <p key={i} className="md-bold-para">{line.slice(2, -2)}</p>;
        if (line.startsWith('- ') || line.startsWith('• '))
          return <li key={i} className="md-li">{applyInlineBold(line.slice(2))}</li>;
        if (!line.trim())
          return <div key={i} className="md-spacer" />;
        return <p key={i} className="md-p">{applyInlineBold(line)}</p>;
      })}
    </>
  );
}

function applyInlineBold(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <strong key={i}>{p.slice(2, -2)}</strong>
      : p
  );
}

// ─── Parse report text into named sections ────────────────────────────────────

function parseReport(text) {
  const defs = [
    { key: 'summary',      marker: '## 1. PROPERTY ISSUE SUMMARY' },
    { key: 'observations', marker: '## 2. AREA-WISE OBSERVATIONS' },
    { key: 'rootcause',    marker: '## 3. PROBABLE ROOT CAUSE' },
    { key: 'severity',     marker: '## 4. SEVERITY ASSESSMENT' },
    { key: 'actions',      marker: '## 5. RECOMMENDED ACTIONS' },
    { key: 'notes',        marker: '## 6. ADDITIONAL NOTES' },
    { key: 'missing',      marker: '## 7. MISSING OR UNCLEAR INFORMATION' },
  ];

  const found = [];
  for (const def of defs) {
    let idx = text.indexOf(def.marker);
    if (idx === -1) {
      // Try common LLM variations
      const fallbacks = [
        def.marker.replace('## ', ''),
        def.marker.replace('## ', '# '),
        def.marker.replace('## ', '**') + '**',
      ];
      for (const fb of fallbacks) {
        idx = text.indexOf(fb);
        if (idx !== -1) break;
      }
    }
    if (idx !== -1) found.push({ key: def.key, idx });
  }

  found.sort((a, b) => a.idx - b.idx);

  const sections = {};
  for (let i = 0; i < found.length; i++) {
    const start = found[i].idx;
    const end   = i + 1 < found.length ? found[i + 1].idx : undefined;
    let content = text.slice(start, end);
    // Remove the header line
    content = content.replace(/^[#*\s]*\d+\.\s[^\n]+\n/, '').trim();
    sections[found[i].key] = content;
  }

  if (Object.keys(sections).length === 0) {
    sections.summary = text;
  }

  return sections;
}

// ─── Download as standalone HTML ──────────────────────────────────────────────

function buildDownloadHTML(reportText, images) {
  const imgMap = buildImageMap(images);
  const parts  = reportText.split(/(\{IMAGE:[^}]+\})/g);
  let htmlBody = '';

  parts.forEach(part => {
    const match = part.match(/^\{IMAGE:([^}]+)\}$/);
    if (match) {
      const imgId = match[1].trim();
      const img   = imgMap[imgId];
      if (img) {
        htmlBody += `<div style="margin:12px 0;">
          <img src="data:${img.mime_type};base64,${img.data}"
               style="max-width:420px;border:1px solid #ddd;border-radius:8px;display:block;"/>
          <div style="font-size:11px;color:#666;margin-top:4px;">
            ${typeLabel(img.img_type)} · ${img.source} · Page ${img.page}
          </div>
        </div>`;
      } else {
        htmlBody += `<div style="color:#c0392b;font-size:12px;margin:8px 0;">
          ⚠ Image Not Available: ${imgId}
        </div>`;
      }
    } else {
      let e = part
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      e = e.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      e = e.replace(/^### (.+)$/mg, '<h3 style="color:#1a7a5e;margin:14px 0 4px;">$1</h3>');
      e = e.replace(/^## (.+)$/mg,  '<h2 style="color:#1a4a5e;border-bottom:1px solid #ddd;padding-bottom:6px;margin:22px 0 10px;">$1</h2>');
      e = e.replace(/^- (.+)$/mg,   '<li style="margin:3px 0;">$1</li>');
      e = e.replace(/^\|(.+)\|$/mg, '<div style="font-family:monospace;font-size:12px;background:#f5f5f5;padding:2px 6px;">|$1|</div>');
      htmlBody += `<div style="line-height:1.7;">${e}</div>`;
    }
  });

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>DDR Report ${new Date().toISOString().slice(0,10)}</title>
<style>
  body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:24px;color:#222;font-size:14px;line-height:1.7;}
  h1{color:#1a4a5e;border-bottom:3px solid #1a7a5e;padding-bottom:10px;}
  img{max-width:100%;border-radius:6px;}
  li{margin:4px 0;}
</style>
</head>
<body>
  <h1>Detailed Diagnostic Report (DDR)</h1>
  <p style="color:#888;font-size:12px;">Generated: ${new Date().toLocaleString()}</p>
  <hr/>
  ${htmlBody}
  <hr style="margin-top:40px;"/>
  <p style="font-size:11px;color:#aaa;text-align:center;">Generated by DDR Report Generator</p>
</body>
</html>`;
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [inspFile,    setInspFile]    = useState(null);
  const [thermalFile, setThermalFile] = useState(null);
  const [apiKey,      setApiKey]      = useState('');
  const [loading,     setLoading]     = useState(false);
  const [statusMsg,   setStatusMsg]   = useState('');
  const [result,      setResult]      = useState(null);
  const [rawReport,   setRawReport]   = useState('');
  const [viewMode,    setViewMode]    = useState('structured');
  const [copied,      setCopied]      = useState(false);
  const [activeImg,   setActiveImg]   = useState(null);

  const canGenerate = inspFile && thermalFile && apiKey.startsWith('gsk_');

  const generate = async () => {
    if (!canGenerate) return;
    setLoading(true);
    setResult(null);
    setRawReport('');
    setStatusMsg('Uploading documents and extracting content…');

    const formData = new FormData();
    formData.append('inspection_report', inspFile);
    formData.append('thermal_report',    thermalFile);
    formData.append('api_key',           apiKey);

    try {
      setStatusMsg('Analysing documents with Groq AI…');
      const resp = await fetch(`${API_BASE}/generate-ddr`, {
        method: 'POST',
        body:   formData,
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
    const html = buildDownloadHTML(rawReport, result?.images || []);
    const blob = new Blob([html], { type: 'text/html' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `DDR_Report_${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const sections = result ? parseReport(result.report) : {};
  const imageMap = buildImageMap(result?.images);

  return (
    <div className="app-root">

      {/* Header */}
      <header className="app-header">
        <div className="header-inner">
          <div className="logo-mark">DDR</div>
          <div>
            <h1 className="app-title">Detailed Diagnostic Report Generator</h1>
            <p className="app-subtitle">Professional inspection analysis &amp; diagnostic reporting</p>
          </div>
        </div>
      </header>

      <main className="main-content">

        {/* Input Panel */}
        <section className="panel input-panel">
          <h2 className="panel-heading">Upload Documents</h2>
          <p className="panel-sub">Supports PDF files (Inspection Report + Thermal Report)</p>

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
            <label className="api-label">Groq API Key</label>
            <input
              className="api-input"
              type="password"
              placeholder="gsk_..."
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              autoComplete="off"
            />
          </div>
          <p className="api-hint">Get a free key at console.groq.com — never stored on our servers.</p>

          <button
            className={`gen-btn ${loading ? 'loading' : ''}`}
            onClick={generate}
            disabled={!canGenerate || loading}
          >
            {loading
              ? <><span className="spinner" /> Generating Report…</>
              : <><span className="btn-icon">⚡</span> Generate DDR Report</>
            }
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

            {/* Stats */}
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
                <span className="stat-val">{result.stats.thermal_scans}</span>
                <span className="stat-label">Thermal scans</span>
              </div>
              <div className="stat-item">
                <span className="stat-val">{result.stats.visual_photos}</span>
                <span className="stat-label">Visual photos</span>
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
                  ⬇ Download .html
                </button>
              </div>
            </div>

            {/* Extracted Images Gallery */}
            {result.images && result.images.length > 0 && (
              <div className="images-gallery">
                <h3 className="gallery-heading">
                  Extracted Images ({result.images.length}) — click to enlarge
                </h3>
                {/* Group by type */}
                {['inspection_photo', 'thermal_scan', 'visual_photo'].map(type => {
                  const group = result.images.filter(img => img.img_type === type);
                  if (!group.length) return null;
                  return (
                    <div key={type} style={{ marginBottom: 12 }}>
                      <div
                        style={{
                          display: 'inline-block',
                          background: typeBadgeColor(type),
                          color: '#fff',
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 10px',
                          borderRadius: 10,
                          marginBottom: 8,
                        }}
                      >
                        {typeLabel(type)} ({group.length})
                      </div>
                      <div className="img-thumbs">
                        {group.map(img => (
                          <div
                            key={img.id}
                            className="img-thumb"
                            onClick={() => setActiveImg(img)}
                            title={img.id}
                          >
                            <img
                              src={`data:${img.mime_type};base64,${img.data}`}
                              alt={img.id}
                            />
                            <div className="img-thumb-label">{img.source} p.{img.page}</div>
                            <div className="img-thumb-source">{img.img_type.replace('_', ' ')}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Structured View */}
            {viewMode === 'structured' && (
              <div className="structured-report">
                {[
                  { key: 'summary',      num: '1', title: 'Property Issue Summary' },
                  { key: 'observations', num: '2', title: 'Area-wise Observations' },
                  { key: 'rootcause',    num: '3', title: 'Probable Root Cause' },
                  { key: 'severity',     num: '4', title: 'Severity Assessment' },
                  { key: 'actions',      num: '5', title: 'Recommended Actions' },
                  { key: 'notes',        num: '6', title: 'Additional Notes' },
                  { key: 'missing',      num: '7', title: 'Missing or Unclear Information' },
                ].map(({ key, num, title }) =>
                  sections[key] ? (
                    <ReportSection key={key} num={num} title={title}>
                      <ReportWithImages
                        text={sections[key]}
                        imageMap={imageMap}
                        onImageClick={setActiveImg}
                      />
                    </ReportSection>
                  ) : null
                )}

                {Object.keys(sections).length === 0 && (
                  <pre className="raw-report">{rawReport}</pre>
                )}
              </div>
            )}

            {/* Raw View */}
            {viewMode === 'raw' && (
              <pre className="raw-report">{rawReport}</pre>
            )}

          </section>
        )}
      </main>

      {/* Lightbox */}
      {activeImg && (
        <div className="lightbox" onClick={() => setActiveImg(null)}>
          <div className="lightbox-inner" onClick={e => e.stopPropagation()}>
            <button className="lightbox-close" onClick={() => setActiveImg(null)}>✕</button>
            <img
              src={`data:${activeImg.mime_type};base64,${activeImg.data}`}
              alt={activeImg.id}
            />
            <div className="lightbox-meta">
              <span
                style={{
                  background: typeBadgeColor(activeImg.img_type),
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: 8,
                  marginRight: 8,
                }}
              >
                {typeLabel(activeImg.img_type)}
              </span>
              {activeImg.id} · {activeImg.source} · Page {activeImg.page} · {activeImg.size_kb} KB
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
