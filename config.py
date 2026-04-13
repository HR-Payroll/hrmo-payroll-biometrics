DEVICES = [
    {"id": "device_1", "ip": "192.168.1.201", "port": 4370, "password": 0, "timeout": 5},
    {"id": "device_2", "ip": "192.168.1.202", "port": 4370, "password": 0, "timeout": 5},
]

DB_PATH             = "data/events.db"
LOG_PATH            = "logs/server.log"
LOG_MAX_MB          = 2
LOG_BACKUPS         = 3
RECONNECT_BASE_DELAY = 5   # seconds; doubles each retry, capped at 60s
LIVE_TIMEOUT        = 10   # seconds; pyzk live_capture timeout
API_PORT            = 8000
