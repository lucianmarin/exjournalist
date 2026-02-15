from app.config import DEBUG

bind = "127.0.0.1:8000" if DEBUG else "unix:exj.socket"
pidfile = "exj.pid"
workers = 1 if DEBUG else 3
reload = DEBUG
