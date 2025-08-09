# comicbook-api
 A FastAPI-powered server for generating AI-illustrated comic book pages from custom prompts, styles, and character references. Supports image uploads, multiple page definitions, and PDF/ZIP export.

## Run
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn api:app --reload --port 8000
