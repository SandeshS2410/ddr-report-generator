import React, { useState, useCallback, useRef } from 'react';
import './App.css';

const API_BASE = process.env.REACT_APP_API_URL || '';

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
    { key: 'summary', markers: ['1. PROPERTY ISSUE SUMMARY', '## 1.', '#1.', '**1.'] },
    { key: 'observations', markers: ['2. AREA-WISE OBSERVATIONS', '## 2.', '#2.', '**2.'] },
    { key: 'rootcause', markers: ['3. PROBABLE ROOT CAUSE', '## 3.', '#3.', '**3.'] },
    { key: 'severity', markers: ['4. SEVERITY ASSESSMENT', '## 4.', '#4.', '**4.'] },
    { key: 'actions', markers: ['5. RECOMMENDED ACTIONS', '## 5.', '#5.', '**5.'] },
    { key: 'notes', markers: ['6. ADDITIONAL NOTES', '## 6.', '#6.', '**6.'] },
    { key: 'missing', markers: ['7. MISSING OR UNCLEAR INFORMATION', '## 7.', '#7.', '**7.'] },
  ];

  const sectionStarts = [];
  for (const { key, markers } of patterns) {
    for (const marker of markers) {
      const idx = text.indexOf(marker);
      if (idx !== -1) {
        sectionStarts.push({ key, idx });
        break;
      }
    }
  }

  sectionStarts.sort((a, b) => a.idx - b.idx);

  for (let i = 0; i < sectionStarts.length; i++) {
    const start = sectionStarts[i].idx;
    const end = i + 1 < sectionStarts.length ? sectionStarts[i + 1].idx : undefined;
    const content = text.slice(start, end).replace(/^[#*\s]*\d+\.\s*/m, '').trim();
    sections[sectionStarts[i].key] = content;
  }

  return sections;
}

// ─── Render report text with inline images ────────────────────────────────────
function ReportWithImages({ text, images }) {
  if (!images || images.length === 0) {
    return <pre className="section-pre">{text}</pre>;
  }

  // Build a map of image id -> image object
  const imgMap = {};
  images.forEach(img => { imgMap[img.id] = img; });

  // Split text by image references like [Inspection_p1_img1]
  const parts = text.split(/(\[[^\]]+\])/g);

  return (
    <div className="section-pre" style={{ whiteSpace: 'pre-wrap' }}>
      {parts.map((part, i) => {
        const match = part.match(/^\[([^\]]+)\]$/);
        if (match) {
          const imgId = match[1];
          const img = imgMap[imgId];
          if (img) {
            return (
              <div key={i} style={{ margin: '8px 0' }}>
                <img
                  src={`data:${img.mime_type};base64,${img.data}`}
                  alt={imgId}
                  style={{ maxWidth: '340px', borderRadius: '6px', border: '1px solid #333', display: 'block' }}
                />
                <div style={{ fontSize: '11px', color: '#4fd1a5', marginTop: '4px' }}>{imgId} · {img.source} · Page {img.page}</div>
              </div>
            );
          }
        }
        return <span key={i}>{part}</span>;
      })}
    </div>
  );
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
  const [viewMode, setViewMode] = useState('structured');
  const [copied, setCopied] = useState(false);
  const [activeImg, setActiveImg] = useState(null);

  const canGenerate = inspFile && thermalFile && apiKey.startsWith('gsk_');

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
      setStatusMsg('Analysing documents with Groq AI…');
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
    // Build image map
    const imgMap = {};
    if (result && result.images) {
      result.images.forEach(img => { imgMap[img.id] = img; });
    }

    // Convert report text to HTML with embedded images
    let htmlBody = '';
    const lines = rawReport.split('\n');

    lines.forEach(line => {
      // Replace image references inline
      const parts = line.split(/(\[[^\]]+\])/g);
      let lineHtml = '';
      parts.forEach(part => {
        const match = part.match(/^\[([^\]]+)\]$/);
        if (match && imgMap[match[1]]) {
          const img = imgMap[match[1]];
          lineHtml += `<div style="margin:8px 0;">
            <img src="data:${img.mime_type};base64,${img.data}" 
                 style="max-width:400px;border:1px solid #ddd;border-radius:6px;display:block;" 
                 alt="${img.id}"/>
            <div style="font-size:11px;color:#666;margin-top:3px;">${img.id} · ${img.source} · Page ${img.page}</div>
          </div>`;
        } else {
          // Escape HTML and style markdown
          let escaped = part
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
          // Bold text
          escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
          // Headers
          escaped = escaped.replace(/^#{1,3}\s*(.+)/, '<strong style="font-size:15px;">$1</strong>');
          lineHtml += escaped;
        }
      });
      htmlBody += `<div style="min-height:1.5em;">${lineHtml}</div>`;
    });

    // Add all images section at the bottom
    let allImagesSection = '';
    if (result && result.images && result.images.length > 0) {
      allImagesSection = `
        <hr style="margin:40px 0;border:1px solid #eee;"/>
        <h2 style="color:#1a7a5e;">All Extracted Images (${result.images.length})</h2>
        <div style="display:flex;flex-wrap:wrap;gap:12px;margin-top:16px;">
          ${result.images.map(img => `
            <div style="text-align:center;">
              <img src="data:${img.mime_type};base64,${img.data}" 
                   style="width:160px;height:110px;object-fit:cover;border:1px solid #ddd;border-radius:6px;display:block;"/>
              <div style="font-size:10px;color:#888;margin-top:3px;">${img.id}</div>
              <div style="font-size:10px;color:#aaa;">${img.source} · p.${img.page}</div>
            </div>
          `).join('')}
        </div>`;
    }

    const fullHtml = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>DDR Report - ${new Date().toISOString().slice(0, 10)}</title>
<style>
  body { 
    font-family: Arial, sans-serif; 
    max-width: 960px; 
    margin: 40px auto; 
    padding: 20px; 
    line-height: 1.7; 
    color: #222; 
    font-size: 14px;
  }
  h1 { color: #1a7a5e; border-bottom: 2px solid #1a7a5e; padding-bottom: 8px; }
  img { display: block; }
</style>
</head>
<body>
  <h1>Detailed Diagnostic Report (DDR)</h1>
  <p style="color:#888;font-size:12px;">Generated: ${new Date().toLocaleString()}</p>
  <hr style="border:1px solid #eee;margin:20px 0;"/>
  ${htmlBody}
  ${allImagesSection}
  <hr style="margin:40px 0;border:1px solid #eee;"/>
  <p style="font-size:11px;color:#aaa;text-align:center;">Generated by DDR Report Generator</p>
</body>
</html>`;

    const blob = new Blob([fullHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `DDR_Report_${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
    URL.revokeObjectURL(url);
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
            <p className="app-subtitle">Professional inspection analysis & diagnostic reporting</p>
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
                  ⬇ Download .html
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
                      <img src={`data:${img.mime_type};base64,${img.data}`} alt={img.id} />
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
                    <ReportWithImages text={sections.summary} images={result.images} />
                  </ReportSection>
                )}
                {sections.observations && (
                  <ReportSection num="2" title="Area-wise Observations">
                    <ReportWithImages text={sections.observations} images={result.images} />
                  </ReportSection>
                )}
                {sections.rootcause && (
                  <ReportSection num="3" title="Probable Root Cause">
                    <ReportWithImages text={sections.rootcause} images={result.images} />
                  </ReportSection>
                )}
                {sections.severity && (
                  <ReportSection num="4" title="Severity Assessment">
                    <ReportWithImages text={sections.severity} images={result.images} />
                  </ReportSection>
                )}
                {sections.actions && (
                  <ReportSection num="5" title="Recommended Actions">
                    <ReportWithImages text={sections.actions} images={result.images} />
                  </ReportSection>
                )}
                {sections.notes && (
                  <ReportSection num="6" title="Additional Notes">
                    <ReportWithImages text={sections.notes} images={result.images} />
                  </ReportSection>
                )}
                {sections.missing && (
                  <ReportSection num="7" title="Missing or Unclear Information">
                    <ReportWithImages text={sections.missing} images={result.images} />
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
            <img src={`data:${activeImg.mime_type};base64,${activeImg.data}`} alt={activeImg.id} />
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