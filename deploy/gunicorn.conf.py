# Gunicorn configuration for Tecnipro Dashboard — production

bind = "127.0.0.1:5001"
workers = 2
worker_class = "sync"
timeout = 300
keepalive = 5
max_requests = 1000
max_requests_jitter = 50

accesslog = "/var/log/tecnipro/gunicorn-access.log"
errorlog = "/var/log/tecnipro/gunicorn-error.log"
loglevel = "info"

preload_app = True
