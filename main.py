import streamlit as st
import docx
import requests
import json
import io
import re
import hashlib
import bleach
from xhtml2pdf import pisa

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Resume Optimizer",
    page_icon="🪄",
    layout="wide"
)

# Limits
RESUME_MAX_CHARS  = 15_000   # ~3,750 tokens — keeps prompt safe
JD_MAX_CHARS      = 8_000    # ~2,000 tokens
RESUME_MIN_CHARS  = 100      # anything below this is probably junk
API_TIMEOUT_SECS  = 60       # long enough for generation; short enough to fail fast

# HTML allowlist  (enforced by bleach after AI output arrives)
ALLOWED_TAGS = ["h1", "h2", "h3", "p", "strong", "em", "ul", "li"]
ALLOWED_ATTRS = {}           # no attributes at all — safest default


# ─────────────────────────────────────────────
# PHASE 6  — DOCX EXTRACTION
# ─────────────────────────────────────────────

def extract_text_from_docx(uploaded_file) -> tuple[str | None, str | None]:
    """
    Extracts text from paragraphs AND table cells.

    Returns
    -------
    (text, error_message)
    """
    try:
        doc = docx.Document(uploaded_file)
        parts: list[str] = []

        # Paragraphs
        for para in doc.paragraphs:
            stripped = para.text.strip()
            if stripped:
                parts.append(stripped)

        # Tables  (common in professional resume templates)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    stripped = cell.text.strip()
                    if stripped and stripped not in parts:   # avoid duplicates
                        parts.append(stripped)

        full_text = "\n".join(parts).strip()
        return full_text, None

    except Exception as exc:
        return None, f"Could not read the DOCX file: {exc}"


# ─────────────────────────────────────────────
# PHASE 7  — INPUT VALIDATION
# ─────────────────────────────────────────────

def validate_resume_text(text: str) -> tuple[bool, str]:
    """
    Returns (is_valid, user_facing_message).
    """
    if not text:
        return False, (
            "No text could be extracted from the uploaded file. "
            "The document may be empty, image-only, or heavily formatted. "
            "Try copying the content into a plain DOCX and re-uploading."
        )

    if len(text) < RESUME_MIN_CHARS:
        return False, (
            f"The extracted resume text is too short ({len(text)} characters). "
            "Check that the DOCX contains readable text and is not a scanned image."
        )

    if len(text) > RESUME_MAX_CHARS:
        return False, (
            f"The resume is very long ({len(text):,} characters). "
            f"Please trim it to under {RESUME_MAX_CHARS:,} characters to stay within "
            "the AI model's limit."
        )

    return True, ""


def validate_jd_text(text: str) -> tuple[bool, str]:
    """
    Returns (is_valid, user_facing_message).
    """
    stripped = text.strip()
    if not stripped:
        return False, "The job description is empty. Please paste the full JD text."

    if len(stripped) > JD_MAX_CHARS:
        return False, (
            f"The job description is very long ({len(stripped):,} characters). "
            f"Please shorten it to under {JD_MAX_CHARS:,} characters."
        )

    return True, ""


# ─────────────────────────────────────────────
# PHASE 1  — SAFE API LAYER
# ─────────────────────────────────────────────

def _extract_api_error(response: requests.Response) -> str:
    """
    Tries to pull a structured error message from a Gemini error response.
    Falls back to a generic label if the body is not valid JSON.
    """
    try:
        body = response.json()
        # Gemini error envelope: {"error": {"message": "...", "status": "..."}}
        return body.get("error", {}).get("message", "Unknown API error.")
    except Exception:
        # Body is not JSON — return a safe truncated snippet
        snippet = response.text[:200].strip() if response.text else "(empty body)"
        return f"Unexpected API response: {snippet}"


def call_gemini_api(
    api_key: str,
    resume_text: str,
    jd_text: str,
) -> tuple[dict | None, str | None]:
    """
    Makes the HTTP call to Gemini and returns (parsed_json, error_message).

    Separates four failure classes:
        1. Connection failure  (no network / DNS)
        2. Timeout             (server too slow)
        3. HTTP status error   (4xx / 5xx)
        4. Invalid JSON body   (response is not parseable)
    """
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

    # ── 1. Connection failure ──────────────────────────────────────────────
    try:
        response = requests.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=API_TIMEOUT_SECS,
        )
    except requests.exceptions.ConnectionError:
        return None, (
            "Could not reach the Gemini API. "
            "Check your internet connection and try again."
        )
    # ── 2. Timeout ────────────────────────────────────────────────────────
    except requests.exceptions.Timeout:
        return None, (
            f"The AI request timed out after {API_TIMEOUT_SECS} seconds. "
            "The service may be busy. Please try again in a moment."
        )
    # ── Catch-all for other requests-level errors ─────────────────────────
    except requests.exceptions.RequestException as exc:
        return None, f"Network error: {exc}"

    # ── 3. HTTP status failure ────────────────────────────────────────────
    if not response.ok:
        error_detail = _extract_api_error(response)
        status = response.status_code

        if status == 400:
            return None, f"Bad request sent to Gemini API: {error_detail}"
        if status == 401:
            return None, (
                "Authentication failed. "
                "Your Gemini API key appears to be invalid. "
                "Double-check the key in the sidebar."
            )
        if status == 403:
            return None, (
                "Access denied. "
                "Your API key may not have permission to use this model."
            )
        if status == 429:
            return None, (
                "Rate limit reached. "
                "You have made too many requests. "
                "Wait a minute and try again."
            )
        if status >= 500:
            return None, (
                "The Gemini service returned a server error "
                f"(HTTP {status}). Try again shortly."
            )
        return None, f"Unexpected HTTP {status}: {error_detail}"

    # ── 4. Invalid JSON body ───────────────────────────────────────────────
    try:
        data = response.json()
    except Exception:
        return None, (
            "The API returned a response that could not be parsed. "
            "This is unusual — please try again."
        )

    return data, None


# ─────────────────────────────────────────────
# PHASE 2  — SAFE RESPONSE PARSING
# ─────────────────────────────────────────────

def parse_gemini_response(data: dict) -> tuple[str | None, str | None]:
    """
    Validates the Gemini response structure before reading from it.

    Returns (raw_html_text, error_message).
    """

    # ── Step 4: Structural validation ─────────────────────────────────────
    candidates = data.get("candidates")
    if not candidates or not isinstance(candidates, list):
        return None, (
            "The AI returned a response with no candidates. "
            "This can happen when the input is flagged or the model fails internally. "
            "Try shortening the resume or job description."
        )

    first = candidates[0]
    if not isinstance(first, dict):
        return None, "The AI response structure was unexpected. Please try again."

    content = first.get("content")
    if not content or not isinstance(content, dict):
        # Check for a finish reason that might explain why content is missing
        finish_reason = first.get("finishReason", "UNKNOWN")
        if finish_reason in ("SAFETY", "RECITATION"):
            return None, (
                "The AI declined to generate output for this content "
                f"(reason: {finish_reason}). "
                "Try rewording the job description or resume."
            )
        return None, (
            f"The AI response had no content block (finish reason: {finish_reason}). "
            "Please try again."
        )

    parts = content.get("parts")
    if not parts or not isinstance(parts, list):
        return None, "The AI response contained no text parts. Please try again."

    raw_text = parts[0].get("text") if isinstance(parts[0], dict) else None
    if raw_text is None:
        return None, "The AI response text field was missing. Please try again."

    # ── Step 5: Empty / blocked output ────────────────────────────────────
    stripped = raw_text.strip()
    if not stripped:
        return None, (
            "The AI returned an empty response. "
            "Try again, or shorten the input text."
        )

    # Detect common refusal / safety phrases as a best-effort check
    refusal_signals = [
        "i cannot", "i'm unable", "i am unable",
        "i can't", "i won't", "i will not",
        "as an ai", "i don't have the ability",
    ]
    lower = stripped.lower()
    if any(signal in lower for signal in refusal_signals) and len(stripped) < 400:
        return None, (
            "The AI refused to generate the resume. "
            "Try adjusting the resume text or job description."
        )

    return stripped, None


# ─────────────────────────────────────────────
# PHASE 3  — HTML CLEANING & VALIDATION
# ─────────────────────────────────────────────

def clean_markdown_fences(text: str) -> str:
    """
    Removes all common markdown code-fence patterns.

    Handles:
        ```html ... ```
        ``` ... ```
        fences with leading/trailing whitespace
        preamble lines before the first HTML tag
    """
    # Remove opening fence:  ```html  or  ```  (with optional whitespace)
    text = re.sub(r"^\s*```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    # Remove closing fence
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)

    # If there is still a leading line of prose before the first tag, drop it
    # e.g. "Here is your optimized resume:\n<h1>..."
    first_tag = re.search(r"<[a-zA-Z]", text)
    if first_tag and first_tag.start() > 0:
        text = text[first_tag.start():]

    return text.strip()


def sanitize_html(raw_html: str) -> str:
    """
    Strips every tag and attribute not on the allowlist using bleach.
    This is the single enforcement point for the HTML allowlist.
    """
    return bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,          # remove disallowed tags entirely (not escape them)
        strip_comments=True,
    )


def validate_html_content(html: str) -> tuple[bool, str]:
    """
    Confirms the sanitized HTML is non-empty and contains meaningful structure.

    Returns (is_valid, user_facing_message).
    """
    stripped = html.strip()

    if not stripped:
        return False, (
            "The AI output contained no usable HTML after cleanup. "
            "Please try again."
        )

    # Must contain at least one expected structural element
    has_structure = bool(
        re.search(r"<(h[123]|p|li)\b", stripped, re.IGNORECASE)
    )
    if not has_structure:
        return False, (
            "The AI output did not contain recognisable resume sections. "
            "Try again or simplify the job description."
        )

    # Sanity-check: meaningful text should be present (strip all tags, check length)
    text_only = re.sub(r"<[^>]+>", "", stripped)
    if len(text_only.strip()) < 50:
        return False, (
            "The AI returned HTML with very little text. "
            "Try again or check that the resume DOCX contains readable content."
        )

    return True, ""


def process_ai_html(raw_text: str) -> tuple[str | None, str | None]:
    """
    Full pipeline: fence removal → sanitization → validation.

    Returns (clean_html, error_message).
    """
    # Step 6 — strip fences
    no_fences = clean_markdown_fences(raw_text)

    # Step 7 — allowlist enforcement
    sanitized = sanitize_html(no_fences)

    # Step 8 — structural validation
    is_valid, msg = validate_html_content(sanitized)
    if not is_valid:
        return None, msg

    return sanitized, None


# ─────────────────────────────────────────────
# PHASE 4  — PDF GENERATION
# ─────────────────────────────────────────────

# Professional CSS kept in one place for easy editing
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
li     { margin-bottom: 5pt; text-align: left; }
strong { font-weight: bold; color: #000; }
em     { font-style: italic; color: #444; }
"""


def generate_pdf(clean_html: str) -> tuple[bytes | None, str | None]:
    """
    Converts validated, sanitized HTML to a PDF byte stream.

    Returns (pdf_bytes, error_message).
    Only call this after process_ai_html() has already accepted the content.
    """
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
        return None, f"PDF renderer raised an unexpected error: {exc}"

    if status.err:
        return None, (
            "The PDF renderer could not process the HTML. "
            "The resume was generated successfully but could not be exported. "
            "You can copy the preview text manually."
        )

    pdf_bytes = buffer.getvalue()
    if not pdf_bytes:
        return None, "PDF generation produced an empty file. Please try again."

    return pdf_bytes, None


# ─────────────────────────────────────────────
# PHASE 5  — SESSION-STATE HELPERS
# ─────────────────────────────────────────────

def _input_fingerprint(uploaded_file, jd_text: str, api_key: str) -> str:
    """
    Creates a short hash that uniquely identifies the current combination
    of inputs.  When this changes, cached results must be discarded.
    """
    file_bytes = uploaded_file.getvalue() if uploaded_file else b""
    raw = file_bytes + jd_text.encode() + api_key.encode()
    return hashlib.md5(raw).hexdigest()


def clear_stale_results(current_fingerprint: str) -> None:
    """
    Wipes stored output when the user has changed any input since the
    last successful run.
    """
    if st.session_state.get("input_fingerprint") != current_fingerprint:
        for key in ("optimized_html", "pdf_bytes", "input_fingerprint"):
            st.session_state.pop(key, None)


def store_results(html: str, pdf: bytes, fingerprint: str) -> None:
    st.session_state["optimized_html"]    = html
    st.session_state["pdf_bytes"]         = pdf
    st.session_state["input_fingerprint"] = fingerprint


# ─────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def run_optimization(uploaded_file, jd_text: str, api_key: str) -> None:
    """
    Full pipeline with per-phase progress feedback.
    Writes results to session state on success; shows errors on failure.
    """

    # ── Phase 8: explicit progress labels ─────────────────────────────────
    progress = st.status("Starting…", expanded=True)

    def step(label: str) -> None:
        progress.update(label=label)

    # ── Step 1: Extract resume ─────────────────────────────────────────────
    step("📄 Reading resume…")
    resume_text, extract_err = extract_text_from_docx(uploaded_file)
    if extract_err:
        progress.update(label="Failed", state="error")
        st.error(extract_err)
        return

    # ── Step 2: Validate resume text ──────────────────────────────────────
    ok, msg = validate_resume_text(resume_text)
    if not ok:
        progress.update(label="Failed", state="error")
        st.error(msg)
        return

    # ── Step 3: Validate JD ───────────────────────────────────────────────
    ok, msg = validate_jd_text(jd_text)
    if not ok:
        progress.update(label="Failed", state="error")
        st.error(msg)
        return

    # ── Step 4: Call Gemini ───────────────────────────────────────────────
    step("🤖 Sending request to Gemini AI…")
    raw_data, api_err = call_gemini_api(api_key, resume_text, jd_text)
    if api_err:
        progress.update(label="Failed", state="error")
        st.error(api_err)
        st.info(
            "💡 Things to try: verify your API key, check your internet "
            "connection, or shorten the resume / job description."
        )
        return

    # ── Step 5: Parse response ────────────────────────────────────────────
    step("📝 Parsing AI response…")
    raw_html, parse_err = parse_gemini_response(raw_data)
    if parse_err:
        progress.update(label="Failed", state="error")
        st.error(parse_err)
        return

    # ── Step 6: Clean & validate HTML ─────────────────────────────────────
    step("🧹 Cleaning and validating output…")
    clean_html, html_err = process_ai_html(raw_html)
    if html_err:
        progress.update(label="Failed", state="error")
        st.error(html_err)
        return

    # ── Step 7: Generate PDF ──────────────────────────────────────────────
    step("📄 Building PDF…")
    pdf_bytes, pdf_err = generate_pdf(clean_html)

    # Store HTML even if PDF failed — user can still see the preview
    fingerprint = _input_fingerprint(uploaded_file, jd_text, api_key)

    if pdf_err:
        # Partial success — save HTML only, surface actionable message
        st.session_state["optimized_html"]    = clean_html
        st.session_state["pdf_bytes"]         = None
        st.session_state["input_fingerprint"] = fingerprint
        progress.update(label="Done with warnings", state="complete")
        st.warning(
            f"✅ Resume generated successfully, but PDF export failed.\n\n"
            f"**Reason:** {pdf_err}\n\n"
            "You can still read and copy the preview below."
        )
        return

    store_results(clean_html, pdf_bytes, fingerprint)
    progress.update(label="✅ Optimisation complete!", state="complete")
    st.success("Your resume has been tailored and is ready to download.")


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────

st.title("🪄 Resume Optimizer")
st.write(
    "Upload your DOCX resume, paste a Job Description, "
    "and let Gemini tailor it for you instantly."
)

# ── Sidebar — API key ──────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input(
        "Gemini API Key",
        type="password",
        help="Get your free key from Google AI Studio (aistudio.google.com).",
    )
    if not api_key:
        st.warning("Enter your Gemini API key to enable the optimizer.")

    st.divider()
    st.caption(
        f"Limits: resume ≤ {RESUME_MAX_CHARS:,} chars · "
        f"JD ≤ {JD_MAX_CHARS:,} chars · "
        f"timeout {API_TIMEOUT_SECS}s"
    )

# ── Main layout ────────────────────────────────────────────────────────────
left, right = st.columns(2, gap="large")

with left:
    st.subheader("1 · Upload Resume")
    uploaded_file = st.file_uploader(
        "Choose a .docx file", type=["docx"], label_visibility="collapsed"
    )
    if uploaded_file:
        st.caption(f"Uploaded: **{uploaded_file.name}**")

    st.subheader("2 · Paste Job Description")
    jd_text = st.text_area(
        "Paste the full requirements and responsibilities here.",
        height=260,
        label_visibility="collapsed",
        placeholder="Paste the job description here…",
    )
    if jd_text:
        st.caption(f"{len(jd_text):,} / {JD_MAX_CHARS:,} characters")

    # ── Stale-result guard ─────────────────────────────────────────────────
    if uploaded_file and jd_text and api_key:
        fingerprint = _input_fingerprint(uploaded_file, jd_text, api_key)
        clear_stale_results(fingerprint)

    can_run = bool(uploaded_file and jd_text.strip() and api_key)
    if st.button(
        "✨ Tailor My Resume",
        type="primary",
        use_container_width=True,
        disabled=not can_run,
    ):
        run_optimization(uploaded_file, jd_text, api_key)

    # Helpful inline hints when not ready
    if not can_run:
        missing = []
        if not uploaded_file:
            missing.append("upload a DOCX resume")
        if not jd_text.strip():
            missing.append("paste the job description")
        if not api_key:
            missing.append("enter your API key in the sidebar")
        if missing:
            st.info("To continue: " + ", ".join(missing) + ".")

with right:
    st.subheader("Optimized Resume Preview")

    html = st.session_state.get("optimized_html")
    pdf  = st.session_state.get("pdf_bytes")

    if html:
        # Safe preview inside an isolated iframe-like component
        st.components.v1.html(
            f"<div style='font-family: sans-serif; padding: 8px;'>{html}</div>",
            height=520,
            scrolling=True,
        )

        st.divider()

        if pdf:
            st.download_button(
                label="📥 Download PDF",
                data=pdf,
                file_name="Optimized_Resume.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.warning(
                "PDF export is unavailable for this result. "
                "You can select and copy the text from the preview above."
            )
    else:
        st.info(
            "Your tailored resume will appear here after you click "
            "**✨ Tailor My Resume**."
        )