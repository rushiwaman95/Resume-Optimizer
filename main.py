# app.py  —  Resume Optimizer (Flask, single-file)
# Requirements:
#   pip install flask python-docx requests bleach xhtml2pdf

from flask import Flask, request, jsonify, send_file, render_template_string
import docx
import requests as req
import json
import io
import re
import bleach
from xhtml2pdf import pisa

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

RESUME_MAX_CHARS = 15_000
JD_MAX_CHARS     = 8_000
RESUME_MIN_CHARS = 100
API_TIMEOUT_SECS = 60

ALLOWED_TAGS  = ["h1", "h2", "h3", "p", "strong", "em", "ul", "li"]
ALLOWED_ATTRS = {}

app = Flask(__name__)

# ─────────────────────────────────────────────
# HTML TEMPLATE  (single-file UI)
# ─────────────────────────────────────────────

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Resume Optimizer</title>
<style>
  /* ── Reset & base ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    background: #f0f2f6;
    color: #1a1a2e;
    min-height: 100vh;
    display: flex;
  }

  /* ── Sidebar ── */
  .sidebar {
    width: 240px;
    min-width: 240px;
    background: #f8f9fb;
    border-right: 1px solid #dde1ea;
    padding: 32px 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .sidebar h2 {
    font-size: 16px;
    font-weight: 700;
    color: #1a1a2e;
    margin-bottom: 4px;
  }

  .sidebar label {
    font-size: 13px;
    font-weight: 600;
    color: #444;
    display: block;
    margin-bottom: 6px;
  }

  .api-key-wrap {
    position: relative;
  }

  .api-key-wrap input {
    width: 100%;
    padding: 8px 36px 8px 10px;
    border: 1px solid #ccc;
    border-radius: 6px;
    font-size: 13px;
    background: #fff;
    outline: none;
    transition: border-color .2s;
  }

  .api-key-wrap input:focus { border-color: #6c63ff; }

  .toggle-eye {
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    cursor: pointer;
    color: #888;
    font-size: 16px;
    user-select: none;
    background: none;
    border: none;
    padding: 0;
    line-height: 1;
  }

  .hint-box {
    background: #fffde7;
    border: 1px solid #f0d060;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 12px;
    color: #7a6000;
    line-height: 1.5;
  }

  .hint-box.info {
    background: #e8f4fd;
    border-color: #b3d9f5;
    color: #1565c0;
  }

  .hint-box.error {
    background: #fff0f0;
    border-color: #f5b3b3;
    color: #b00020;
  }

  .hint-box.success {
    background: #f0fff4;
    border-color: #b2dfdb;
    color: #1b5e20;
  }

  .hint-box.warning {
    background: #fff8e1;
    border-color: #ffe082;
    color: #e65100;
  }

  .sidebar hr {
    border: none;
    border-top: 1px solid #dde1ea;
    margin: 4px 0;
  }

  .limits-text {
    font-size: 11px;
    color: #999;
    line-height: 1.6;
  }

  /* ── Main content ── */
  .main {
    flex: 1;
    padding: 40px 40px 40px 48px;
    overflow-y: auto;
  }

  .main-header h1 {
    font-size: 28px;
    font-weight: 800;
    color: #1a1a2e;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .main-header p {
    margin-top: 8px;
    font-size: 14px;
    color: #555;
  }

  /* ── Two-column layout ── */
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 40px;
    margin-top: 32px;
  }

  .col-left, .col-right {}

  /* ── Section headings ── */
  .section-title {
    font-size: 18px;
    font-weight: 700;
    color: #1a1a2e;
    margin-bottom: 14px;
  }

  /* ── File upload area ── */
  .upload-area {
    border: 2px dashed #c5cae9;
    border-radius: 10px;
    background: #fff;
    padding: 24px 20px;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    margin-bottom: 24px;
    position: relative;
  }

  .upload-area:hover,
  .upload-area.dragover {
    border-color: #6c63ff;
    background: #f5f3ff;
  }

  .upload-area input[type="file"] {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
    width: 100%;
    height: 100%;
  }

  .upload-icon {
    font-size: 28px;
    margin-bottom: 8px;
  }

  .upload-label {
    font-size: 14px;
    font-weight: 600;
    color: #333;
  }

  .upload-sub {
    font-size: 12px;
    color: #888;
    margin-top: 4px;
  }

  .file-chosen {
    font-size: 12px;
    color: #6c63ff;
    margin-top: 8px;
    font-weight: 600;
  }

  /* ── Textarea ── */
  textarea {
    width: 100%;
    height: 260px;
    border: 1px solid #ccc;
    border-radius: 8px;
    padding: 12px 14px;
    font-size: 13px;
    font-family: inherit;
    resize: vertical;
    background: #fafafa;
    color: #222;
    outline: none;
    transition: border-color .2s;
    line-height: 1.55;
  }

  textarea:focus { border-color: #6c63ff; background: #fff; }

  .char-count {
    font-size: 11px;
    color: #999;
    text-align: right;
    margin-top: 4px;
  }

  .char-count.warn { color: #e65100; }

  /* ── Button ── */
  .btn-primary {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 13px 20px;
    margin-top: 16px;
    background: linear-gradient(135deg, #6c63ff 0%, #48c6ef 100%);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity .2s, transform .1s;
    letter-spacing: .3px;
  }

  .btn-primary:hover:not(:disabled) { opacity: .9; transform: translateY(-1px); }
  .btn-primary:active:not(:disabled) { transform: translateY(0); }

  .btn-primary:disabled {
    background: #c5cae9;
    cursor: not-allowed;
    opacity: .7;
  }

  /* ── Download button ── */
  .btn-download {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 12px 20px;
    margin-top: 16px;
    background: #1b5e20;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    text-decoration: none;
    transition: background .2s;
  }

  .btn-download:hover { background: #2e7d32; }

  /* ── Progress / status ── */
  .status-box {
    display: none;
    margin-top: 14px;
    padding: 12px 14px;
    border-radius: 8px;
    background: #e8f4fd;
    border: 1px solid #b3d9f5;
    color: #1565c0;
    font-size: 13px;
    align-items: center;
    gap: 10px;
  }

  .status-box.visible { display: flex; }

  .spinner {
    width: 18px;
    height: 18px;
    border: 3px solid #b3d9f5;
    border-top-color: #1565c0;
    border-radius: 50%;
    animation: spin .8s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Preview panel ── */
  .preview-panel {
    background: #fff;
    border: 1px solid #dde1ea;
    border-radius: 10px;
    min-height: 420px;
    overflow: hidden;
    position: sticky;
    top: 20px;
  }

  .preview-placeholder {
    display: flex;
    align-items: center;
    padding: 20px;
    height: 100%;
    min-height: 100px;
  }

  .preview-iframe-wrap {
    padding: 0;
    height: 520px;
  }

  .preview-iframe-wrap iframe {
    width: 100%;
    height: 100%;
    border: none;
  }

  .preview-actions {
    border-top: 1px solid #dde1ea;
    padding: 14px 20px;
  }

  /* ── Steps progress bar ── */
  .steps-container {
    display: none;
    margin-top: 14px;
    flex-direction: column;
    gap: 6px;
  }

  .steps-container.visible { display: flex; }

  .step-item {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
    color: #aaa;
    transition: color .3s;
  }

  .step-item.done   { color: #2e7d32; }
  .step-item.active { color: #1565c0; font-weight: 600; }
  .step-item.error  { color: #b00020; }

  .step-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ccc;
    flex-shrink: 0;
    transition: background .3s;
  }

  .step-item.done   .step-dot { background: #2e7d32; }
  .step-item.active .step-dot { background: #1565c0; }
  .step-item.error  .step-dot { background: #b00020; }

  /* ── Responsive ── */
  @media (max-width: 900px) {
    .columns { grid-template-columns: 1fr; }
    .sidebar { width: 200px; min-width: 200px; }
    .main    { padding: 24px 20px; }
  }

  @media (max-width: 640px) {
    body { flex-direction: column; }
    .sidebar {
      width: 100%;
      border-right: none;
      border-bottom: 1px solid #dde1ea;
      padding: 16px;
    }
  }
</style>
</head>
<body>

<!-- ════════════ SIDEBAR ════════════ -->
<aside class="sidebar">
  <div>
    <h2>Settings</h2>
  </div>

  <div>
    <label for="apiKey">Gemini API Key</label>
    <div class="api-key-wrap">
      <input type="password" id="apiKey" placeholder="Paste your key…" autocomplete="off"/>
      <button class="toggle-eye" onclick="toggleKey()" title="Show / Hide" aria-label="Toggle visibility">
        👁
      </button>
    </div>
  </div>

  <div id="apiHint" class="hint-box" style="display:none"></div>

  <hr/>

  <p class="limits-text">
    Limits: resume ≤ 15,000 chars · JD ≤ 8,000 chars · timeout 60s
  </p>
</aside>

<!-- ════════════ MAIN ════════════ -->
<main class="main">

  <div class="main-header">
    <h1>🪄 Resume Optimizer</h1>
    <p>Upload your DOCX resume, paste a Job Description, and let Gemini tailor it for you instantly.</p>
  </div>

  <div class="columns">

    <!-- ── LEFT COLUMN ── -->
    <div class="col-left">

      <p class="section-title">1 · Upload Resume</p>

      <div class="upload-area" id="uploadArea">
        <input type="file" id="fileInput" accept=".docx" onchange="onFileChosen(this)"/>
        <div class="upload-icon">📤</div>
        <div class="upload-label">Click or drag &amp; drop your DOCX</div>
        <div class="upload-sub">Max 15,000 characters · .docx only</div>
        <div class="file-chosen" id="fileChosen"></div>
      </div>

      <p class="section-title">2 · Paste Job Description</p>

      <textarea
        id="jdText"
        placeholder="Paste the job description here…"
        oninput="onJdInput()"
      ></textarea>
      <div class="char-count" id="charCount">0 / 8,000 characters</div>

      <!-- Run button -->
      <button class="btn-primary" id="runBtn" onclick="runOptimization()" disabled>
        ✨ Tailor My Resume
      </button>

      <!-- Inline hint when not ready -->
      <div class="hint-box info" id="missingHint" style="margin-top:12px;">
        To continue: upload a DOCX resume, paste the job description, enter your API key in the sidebar.
      </div>

      <!-- Status / progress -->
      <div class="status-box" id="statusBox">
        <div class="spinner" id="statusSpinner"></div>
        <span id="statusText">Starting…</span>
      </div>

      <!-- Step-by-step progress -->
      <div class="steps-container" id="stepsContainer">
        <div class="step-item" id="step1"><div class="step-dot"></div>📄 Reading resume</div>
        <div class="step-item" id="step2"><div class="step-dot"></div>🤖 Sending to Gemini AI</div>
        <div class="step-item" id="step3"><div class="step-dot"></div>📝 Parsing response</div>
        <div class="step-item" id="step4"><div class="step-dot"></div>🧹 Cleaning HTML output</div>
        <div class="step-item" id="step5"><div class="step-dot"></div>📄 Building PDF</div>
      </div>

      <!-- Result messages -->
      <div class="hint-box" id="resultMsg" style="display:none; margin-top:12px;"></div>

    </div>

    <!-- ── RIGHT COLUMN ── -->
    <div class="col-right">

      <p class="section-title">Optimized Resume Preview</p>

      <div class="preview-panel" id="previewPanel">

        <!-- Placeholder -->
        <div class="preview-placeholder" id="previewPlaceholder">
          <div class="hint-box info" style="width:100%;">
            Your tailored resume will appear here after you click
            <strong>✨ Tailor My Resume</strong>.
          </div>
        </div>

        <!-- iFrame preview (hidden until result ready) -->
        <div class="preview-iframe-wrap" id="previewIframeWrap" style="display:none;">
          <iframe id="previewFrame" title="Resume Preview"></iframe>
        </div>

        <!-- Download button -->
        <div class="preview-actions" id="previewActions" style="display:none;">
          <a href="#" class="btn-download" id="downloadBtn" download="Optimized_Resume.pdf">
            📥 Download PDF
          </a>
        </div>

      </div>

    </div>
  </div>
</main>

<!-- ════════════ JAVASCRIPT ════════════ -->
<script>
"use strict";

// ── state ──────────────────────────────────────────────
let chosenFile = null;

// ── helpers ────────────────────────────────────────────
const $  = id => document.getElementById(id);
const jd = ()  => $("jdText").value;
const key= ()  => $("apiKey").value.trim();

function toggleKey() {
  const inp = $("apiKey");
  inp.type = inp.type === "password" ? "text" : "password";
}

function showApiHint(msg, type = "hint") {
  const el = $("apiHint");
  el.className = "hint-box " + type;
  el.textContent = msg;
  el.style.display = msg ? "block" : "none";
}

function updateReadiness() {
  const hasFile = !!chosenFile;
  const hasJd   = jd().trim().length > 0;
  const hasKey  = key().length > 0;

  $("runBtn").disabled = !(hasFile && hasJd && hasKey);

  // API key hint
  if (!hasKey) {
    showApiHint("Enter your Gemini API key to enable the optimizer.", "");
  } else {
    showApiHint("", "");
  }

  // Missing items hint
  const missing = [];
  if (!hasFile) missing.push("upload a DOCX resume");
  if (!hasJd)   missing.push("paste the job description");
  if (!hasKey)  missing.push("enter your API key in the sidebar");

  const hint = $("missingHint");
  if (missing.length > 0 && !(hasFile && hasJd && hasKey)) {
    hint.textContent = "To continue: " + missing.join(", ") + ".";
    hint.style.display = "block";
  } else {
    hint.style.display = "none";
  }
}

function onFileChosen(input) {
  chosenFile = input.files[0] || null;
  $("fileChosen").textContent = chosenFile ? "✔ " + chosenFile.name : "";
  updateReadiness();
}

function onJdInput() {
  const len  = jd().length;
  const el   = $("charCount");
  el.textContent = len.toLocaleString() + " / 8,000 characters";
  el.className   = len > 8000 ? "char-count warn" : "char-count";
  updateReadiness();
}

$("apiKey").addEventListener("input", updateReadiness);

// drag-and-drop
const ua = $("uploadArea");
["dragenter","dragover"].forEach(ev => ua.addEventListener(ev, e => {
  e.preventDefault(); ua.classList.add("dragover");
}));
["dragleave","drop"].forEach(ev => ua.addEventListener(ev, e => {
  e.preventDefault(); ua.classList.remove("dragover");
}));
ua.addEventListener("drop", e => {
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith(".docx")) {
    chosenFile = f;
    $("fileChosen").textContent = "✔ " + f.name;
    updateReadiness();
  }
});

// ── step progress ──────────────────────────────────────
function resetSteps() {
  for (let i = 1; i <= 5; i++) {
    const el = $("step" + i);
    el.className = "step-item";
  }
}

function setStep(n, state) {   // state: "active" | "done" | "error"
  $("step" + n).className = "step-item " + state;
}

// ── status box ─────────────────────────────────────────
function showStatus(msg) {
  const box = $("statusBox");
  $("statusText").textContent = msg;
  box.classList.add("visible");
}

function hideStatus() {
  $("statusBox").classList.remove("visible");
}

// ── result message ─────────────────────────────────────
function showResult(msg, type) {
  const el = $("resultMsg");
  el.className = "hint-box " + type;
  el.innerHTML = msg;
  el.style.display = "block";
}

function clearResult() {
  $("resultMsg").style.display = "none";
}

// ── preview panel ──────────────────────────────────────
function showPreview(html, pdfUrl) {
  $("previewPlaceholder").style.display = "none";

  const wrap = $("previewIframeWrap");
  wrap.style.display = "block";

  const frame = $("previewFrame");
  const doc = frame.contentDocument || frame.contentWindow.document;
  doc.open();
  doc.write(`
    <!DOCTYPE html><html><head>
    <style>
      body { font-family: sans-serif; padding: 16px; font-size: 13px;
             color: #111; line-height: 1.55; }
      h1 { font-size: 20pt; border-bottom: 2px solid #222;
           padding-bottom: 6px; margin-bottom: 10px; }
      h2 { font-size: 13pt; border-bottom: 1px solid #ccc;
           padding-bottom: 4px; margin-top: 16px; }
      h3 { font-size: 11.5pt; margin-top: 10px; }
      ul { padding-left: 20px; }
      li { margin-bottom: 4px; }
    </style>
    </head><body>${html}</body></html>
  `);
  doc.close();

  const actions = $("previewActions");
  const dlBtn   = $("downloadBtn");
  if (pdfUrl) {
    dlBtn.href = pdfUrl;
    actions.style.display = "block";
  } else {
    actions.style.display = "none";
  }
}

// ── main orchestration ─────────────────────────────────
async function runOptimization() {
  if (!chosenFile) return;

  // Reset UI
  clearResult();
  hideStatus();
  resetSteps();
  $("stepsContainer").classList.add("visible");
  $("runBtn").disabled = true;
  $("previewPlaceholder").style.display = "flex";
  $("previewIframeWrap").style.display  = "none";
  $("previewActions").style.display     = "none";

  const formData = new FormData();
  formData.append("resume", chosenFile);
  formData.append("jd_text", jd());
  formData.append("api_key", key());

  // Step 1 — reading
  setStep(1, "active");
  showStatus("📄 Reading and validating resume…");

  let resp, data;
  try {
    resp = await fetch("/optimize", { method: "POST", body: formData });
    data = await resp.json();
  } catch (err) {
    setStep(1, "error");
    hideStatus();
    showResult("❌ Network error: " + err.message, "error");
    $("runBtn").disabled = false;
    return;
  }

  // Animate steps based on server progress info
  const stepsReached = data.steps_reached || 1;
  for (let i = 1; i <= stepsReached - 1; i++) setStep(i, "done");
  if (!data.ok) {
    setStep(stepsReached, "error");
  } else {
    for (let i = 1; i <= 5; i++) setStep(i, "done");
  }

  hideStatus();

  if (!data.ok) {
    showResult("❌ " + (data.error || "Unknown error."), "error");
    $("runBtn").disabled = false;
    return;
  }

  // Show preview
  showPreview(data.html, data.pdf_url || null);

  if (data.pdf_url) {
    showResult("✅ Your resume has been tailored and is ready to download.", "success");
  } else {
    showResult(
      "✅ Resume generated but PDF export failed.<br>" +
      "<small>" + (data.pdf_warning || "") + "</small>" +
      "<br>You can copy the preview text manually.",
      "warning"
    );
  }

  $("runBtn").disabled = false;
}

// init
updateReadiness();
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
# BACKEND LOGIC  (ported from Streamlit version)
# ─────────────────────────────────────────────

def extract_text_from_docx(file_bytes: bytes) -> tuple:
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        parts = []
        for para in doc.paragraphs:
            s = para.text.strip()
            if s:
                parts.append(s)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    s = cell.text.strip()
                    if s and s not in parts:
                        parts.append(s)
        return "\n".join(parts).strip(), None
    except Exception as exc:
        return None, f"Could not read the DOCX file: {exc}"


def validate_resume_text(text: str) -> tuple:
    if not text:
        return False, (
            "No text could be extracted from the uploaded file. "
            "The document may be empty, image-only, or heavily formatted."
        )
    if len(text) < RESUME_MIN_CHARS:
        return False, (
            f"The extracted resume text is too short ({len(text)} chars). "
            "Check the DOCX contains readable text."
        )
    if len(text) > RESUME_MAX_CHARS:
        return False, (
            f"The resume is very long ({len(text):,} chars). "
            f"Please trim to under {RESUME_MAX_CHARS:,} characters."
        )
    return True, ""


def validate_jd_text(text: str) -> tuple:
    s = text.strip()
    if not s:
        return False, "The job description is empty."
    if len(s) > JD_MAX_CHARS:
        return False, (
            f"The job description is too long ({len(s):,} chars). "
            f"Shorten to under {JD_MAX_CHARS:,} characters."
        )
    return True, ""


def _extract_api_error(response) -> str:
    try:
        body = response.json()
        return body.get("error", {}).get("message", "Unknown API error.")
    except Exception:
        snippet = response.text[:200].strip() if response.text else "(empty body)"
        return f"Unexpected response: {snippet}"


def call_gemini_api(api_key: str, resume_text: str, jd_text: str) -> tuple:
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={api_key}"
    )

    system_prompt = (
        "You are an expert career counselor, executive resume writer, "
        "and ATS optimization specialist.\n"
        "Your objective is to tailor the user's resume to the provided "
        "Job Description (JD).\n\n"
        "Instructions:\n"
        "1. Analyze the JD to identify key skills, required qualifications, "
        "and industry keywords.\n"
        "2. Rewrite the resume to highlight experiences and skills that align "
        "with the JD.\n"
        "3. Improve action verbs, remove fluff, and quantify achievements where possible.\n"
        "4. Output ONLY valid HTML using these tags: "
        "<h1>, <h2>, <h3>, <p>, <strong>, <em>, <ul>, <li>.\n"
        "5. Do NOT wrap output in markdown fences or code blocks.\n"
        "6. Do NOT include <html>, <head>, or <body> tags.\n"
        "7. Do NOT use inline CSS or style attributes.\n"
        "8. Ensure logical hierarchy and no empty elements."
    )

    user_query = (
        f"Here is my current resume:\n\n{resume_text}\n\n"
        f"---\n\nHere is the Job Description I am applying for:\n\n{jd_text}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }

    try:
        response = req.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=API_TIMEOUT_SECS,
        )
    except req.exceptions.ConnectionError:
        return None, "Could not reach the Gemini API. Check your internet connection."
    except req.exceptions.Timeout:
        return None, (
            f"The AI request timed out after {API_TIMEOUT_SECS}s. "
            "The service may be busy — please try again."
        )
    except req.exceptions.RequestException as exc:
        return None, f"Network error: {exc}"

    if not response.ok:
        detail = _extract_api_error(response)
        status = response.status_code
        if status == 400: return None, f"Bad request: {detail}"
        if status == 401: return None, "Invalid API key. Double-check the key in Settings."
        if status == 403: return None, "Access denied. Your key may lack permission for this model."
        if status == 429: return None, "Rate limit reached. Wait a moment and try again."
        if status >= 500: return None, f"Gemini server error (HTTP {status}). Try again shortly."
        return None, f"HTTP {status}: {detail}"

    try:
        return response.json(), None
    except Exception:
        return None, "The API returned an unparseable response. Please try again."


def parse_gemini_response(data: dict) -> tuple:
    candidates = data.get("candidates")
    if not candidates or not isinstance(candidates, list):
        return None, (
            "No candidates in AI response. "
            "Try shortening the resume or job description."
        )
    first = candidates[0]
    if not isinstance(first, dict):
        return None, "Unexpected AI response structure."

    content = first.get("content")
    if not content or not isinstance(content, dict):
        reason = first.get("finishReason", "UNKNOWN")
        if reason in ("SAFETY", "RECITATION"):
            return None, f"AI declined to generate output (reason: {reason})."
        return None, f"No content block in AI response (finish reason: {reason})."

    parts = content.get("parts")
    if not parts or not isinstance(parts, list):
        return None, "No text parts in AI response."

    raw_text = parts[0].get("text") if isinstance(parts[0], dict) else None
    if raw_text is None:
        return None, "Missing text field in AI response."

    stripped = raw_text.strip()
    if not stripped:
        return None, "AI returned an empty response. Try again."

    refusal_signals = [
        "i cannot", "i'm unable", "i am unable",
        "i can't", "i won't", "i will not",
        "as an ai", "i don't have the ability",
    ]
    lower = stripped.lower()
    if any(s in lower for s in refusal_signals) and len(stripped) < 400:
        return None, "AI refused to generate the resume. Try adjusting your inputs."

    return stripped, None


def clean_markdown_fences(text: str) -> str:
    text = re.sub(r"^\s*```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)
    first_tag = re.search(r"<[a-zA-Z]", text)
    if first_tag and first_tag.start() > 0:
        text = text[first_tag.start():]
    return text.strip()


def sanitize_html(raw_html: str) -> str:
    return bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
        strip_comments=True,
    )


def validate_html_content(html: str) -> tuple:
    stripped = html.strip()
    if not stripped:
        return False, "No usable HTML after cleanup. Please try again."
    if not re.search(r"<(h[123]|p|li)\b", stripped, re.IGNORECASE):
        return False, "AI output lacked recognisable resume sections. Try again."
    text_only = re.sub(r"<[^>]+>", "", stripped)
    if len(text_only.strip()) < 50:
        return False, "AI returned HTML with very little text. Try again."
    return True, ""


def process_ai_html(raw_text: str) -> tuple:
    no_fences = clean_markdown_fences(raw_text)
    sanitized = sanitize_html(no_fences)
    ok, msg   = validate_html_content(sanitized)
    if not ok:
        return None, msg
    return sanitized, None


_PDF_CSS = """
@page  { size: A4 portrait; margin: 1.5cm; }
body   { font-family: Helvetica, Arial, sans-serif; color: #111;
         font-size: 11pt; line-height: 1.5; }
h1     { font-size: 22pt; font-weight: bold; margin-bottom: 4pt;
         border-bottom: 2px solid #222; padding-bottom: 6px;
         text-transform: uppercase; color: #000; }
h2     { font-size: 13pt; font-weight: bold; margin-top: 18pt;
         margin-bottom: 10pt; color: #222; text-transform: uppercase;
         border-bottom: 1px solid #ccc; padding-bottom: 4px; }
h3     { font-size: 11.5pt; font-weight: bold; margin-top: 10pt;
         margin-bottom: 2pt; color: #111; }
p      { margin-bottom: 6pt; }
ul     { margin-top: 4pt; margin-bottom: 10pt; padding-left: 20pt; }
li     { margin-bottom: 5pt; }
strong { font-weight: bold; color: #000; }
em     { font-style: italic; color: #444; }
"""


def generate_pdf(clean_html: str) -> tuple:
    full_html = (
        "<html><head>"
        f"<style>{_PDF_CSS}</style>"
        "</head><body>"
        f"{clean_html}"
        "</body></html>"
    )
    buffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(io.StringIO(full_html), dest=buffer)
    except Exception as exc:
        return None, f"PDF renderer error: {exc}"

    if status.err:
        return None, (
            "PDF renderer could not process the HTML. "
            "Resume was generated but PDF export failed."
        )
    pdf_bytes = buffer.getvalue()
    if not pdf_bytes:
        return None, "PDF generation produced an empty file."
    return pdf_bytes, None


# ── in-memory PDF store (simple; per-process) ──────────────
import threading
_pdf_store: dict[str, bytes] = {}
_pdf_lock = threading.Lock()

def store_pdf(pdf_bytes: bytes) -> str:
    import hashlib, time
    key = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]
    with _pdf_lock:
        _pdf_store[key] = pdf_bytes
    return key


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/optimize", methods=["POST"])
def optimize():
    """
    Accepts multipart/form-data with:
        resume  — DOCX file
        jd_text — plain text
        api_key — Gemini key

    Returns JSON:
        { ok, html, pdf_url, error, steps_reached, pdf_warning }
    """

    def fail(msg: str, step: int):
        return jsonify({"ok": False, "error": msg, "steps_reached": step})

    # ── Step 1: Extract ─────────────────────────────────────────────────
    file = request.files.get("resume")
    if not file:
        return fail("No resume file received.", 1)

    file_bytes = file.read()
    resume_text, err = extract_text_from_docx(file_bytes)
    if err:
        return fail(err, 1)

    ok, msg = validate_resume_text(resume_text)
    if not ok:
        return fail(msg, 1)

    jd_text = request.form.get("jd_text", "")
    ok, msg = validate_jd_text(jd_text)
    if not ok:
        return fail(msg, 1)

    api_key = request.form.get("api_key", "").strip()
    if not api_key:
        return fail("No API key provided.", 1)

    # ── Step 2: Call Gemini ─────────────────────────────────────────────
    raw_data, api_err = call_gemini_api(api_key, resume_text, jd_text)
    if api_err:
        return fail(api_err, 2)

    # ── Step 3: Parse ───────────────────────────────────────────────────
    raw_html, parse_err = parse_gemini_response(raw_data)
    if parse_err:
        return fail(parse_err, 3)

    # ── Step 4: Clean HTML ──────────────────────────────────────────────
    clean_html, html_err = process_ai_html(raw_html)
    if html_err:
        return fail(html_err, 4)

    # ── Step 5: Generate PDF ────────────────────────────────────────────
    pdf_bytes, pdf_err = generate_pdf(clean_html)

    if pdf_err:
        return jsonify({
            "ok":           True,
            "html":         clean_html,
            "pdf_url":      None,
            "pdf_warning":  pdf_err,
            "steps_reached": 5,
        })

    pdf_key = store_pdf(pdf_bytes)
    return jsonify({
        "ok":           True,
        "html":         clean_html,
        "pdf_url":      f"/download/{pdf_key}",
        "steps_reached": 5,
    })


@app.route("/download/<key>")
def download_pdf(key: str):
    with _pdf_lock:
        pdf_bytes = _pdf_store.get(key)
    if not pdf_bytes:
        return "PDF not found or expired.", 404
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Optimized_Resume.pdf",
    )


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)