# import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
worker_class = "uvicorn.workers.UvicornWorker"

# כמה workers? כלל אצבע: (CPU cores * 2) או 2–4 להתחלה
timeout = 1800            # hard kill after N seconds of no response
graceful_timeout = 120    # time to gracefully stop workers
keepalive = 75
threads = 2

# הגנות מזליגת זיכרון: ריסטארט worker אחרי X בקשות
max_requests = int(os.getenv("MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("MAX_REQUESTS_JITTER", "100"))

# לוגים בסיסיים (Cloud Run/GKE לוכדים stdout)
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
