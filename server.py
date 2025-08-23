# server.py (repo root)
from app.main import app

# Optional local run:
if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
