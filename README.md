# Resume Optimizer AI 🪄

An intelligent resume optimization tool powered by AI that helps you tailor your resume to job descriptions and improve your chances of landing interviews.

## Features

- **AI-Powered Resume Analysis**: Analyze your resume and compare it with job descriptions
- **Smart Recommendations**: Get actionable suggestions to improve your resume
- **Multiple Format Support**: Upload resumes in DOCX format and extract content automatically
- **Job Description Matching**: Input job descriptions to get customized resume suggestions
- **PDF Export**: Generate and export optimized resumes as PDFs
- **Security Focused**: Input sanitization and validation to ensure safe processing

## Requirements

- Python 3.8 or higher
- Dependencies listed in `requirements.txt`

## Installation

1. Clone or download this project
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application with:
```bash
streamlit run main.py
```

The app will open in your default browser at `http://localhost:8501`

### How to use:

1. **Upload your resume** - Submit a DOCX file containing your resume
2. **Paste job description** - Add the job description you're targeting
3. **Get AI suggestions** - The AI will analyze both and provide optimization recommendations
4. **Export results** - Download your optimized resume as a PDF

## Input Limits

- **Resume**: 100 - 15,000 characters (~3,750 tokens max)
- **Job Description**: Up to 8,000 characters (~2,000 tokens max)
- **API Timeout**: 60 seconds per request

## File Structure

- `main.py` - Main Streamlit application
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Security

The application implements:
- HTML sanitization using bleach library
- Input validation and character limits
- Safe file handling for DOCX documents
- XSS protection through allowed HTML tags whitelist

## License

[Add your license here]

## Support

[Add support information here]
