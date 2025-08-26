# import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
worker_class = "uvicorn.workers.UvicornWorker"

# כמה workers? כלל אצבע: (CPU cores * 2) או 2–4 להתחלה
workers = 2
threads = 2
timeout = 600            # allow long requests
graceful_timeout = 120
keepalive = 5

# הגנות מזליגת זיכרון: ריסטארט worker אחרי X בקשות
max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "100"))

# לוגים בסיסיים (Cloud Run/GKE לוכדים stdout)
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
