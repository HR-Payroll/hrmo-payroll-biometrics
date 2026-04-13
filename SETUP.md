# Biometric Event Server — Setup Guide

Target hardware: Orange Pi (4-core 32-bit ARM, Armbian, 1GB RAM, 16GB SD)

---

## 1. Prerequisites

SSH into your Orange Pi, then run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip sqlite3 -y
```

Verify Python version (3.7+ required):

```bash
python3 --version
```

---

## 2. Create Project User and Directory

Running as a dedicated user limits blast radius if something goes wrong.

```bash
sudo useradd -r -m -s /bin/false biometric
sudo mkdir -p /opt/biometric/data /opt/biometric/logs
```

---

## 3. Copy Project Files

From your development machine, copy the project files to the Orange Pi:

```bash
scp -r /path/to/biometric/* user@<ORANGE_PI_IP>:/tmp/biometric/
```

Then on the Orange Pi, move them into place:

```bash
sudo cp -r /tmp/biometric/* /opt/biometric/
sudo chown -R biometric:biometric /opt/biometric
```

Or if you have git set up:

```bash
sudo -u biometric git clone <your-repo-url> /opt/biometric
```

---

## 4. Configure Device IPs

Edit `config.py` to match your actual ZKTeco devices:

```bash
sudo nano /opt/biometric/config.py
```

Update the `DEVICES` list:

```python
DEVICES = [
    {"id": "device_1", "ip": "192.168.1.201", "port": 4370, "password": 0, "timeout": 5},
    {"id": "device_2", "ip": "192.168.1.202", "port": 4370, "password": 0, "timeout": 5},
]
```

> **Note:** `password` is `0` for most ZKTeco devices unless you explicitly set one. `port` is almost always `4370`.

---

## 5. Create Python Virtual Environment and Install Dependencies

```bash
sudo -u biometric python3 -m venv /opt/biometric/venv
sudo -u biometric /opt/biometric/venv/bin/pip install --upgrade pip
sudo -u biometric /opt/biometric/venv/bin/pip install pyzk
```

Verify pyzk installed correctly:

```bash
sudo -u biometric /opt/biometric/venv/bin/python -c "from zk import ZK; print('pyzk OK')"
```

---

## 6. Test Device Connectivity

Before starting the server, confirm you can reach each device:

```bash
sudo -u biometric /opt/biometric/venv/bin/python -c "
from zk import ZK
zk = ZK('192.168.1.201', port=4370, timeout=5)
conn = zk.connect()
print('Device name:', conn.get_device_name())
conn.disconnect()
"
```

Repeat for `192.168.1.202`. If this fails, check:
- Device is powered on and connected to the same LAN
- IP address is correct (check device menu: Menu → Comm → Ethernet)
- No firewall blocking port `4370` between the Pi and the device

---

## 7. Run Manually to Verify

Before installing as a service, do a quick sanity check:

```bash
cd /opt/biometric
sudo -u biometric /opt/biometric/venv/bin/python main.py
```

You should see log output like:

```
2026-04-10 12:00:00 INFO     main: Biometric Event Server starting
2026-04-10 12:00:00 INFO     device: Connected to device_1 (192.168.1.201:4370)
2026-04-10 12:00:00 INFO     device: Connected to device_2 (192.168.1.202:4370)
2026-04-10 12:00:00 INFO     api: API server listening on port 8000
```

Punch a finger on a device, then in another terminal:

```bash
sqlite3 /opt/biometric/data/events.db "SELECT * FROM events ORDER BY id DESC LIMIT 5;"
```

Press `Ctrl+C` to stop. Confirm the log shows "Shutdown complete" and no events were lost.

---

## 8. Install as systemd Service

```bash
sudo cp /opt/biometric/biometric.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable biometric
sudo systemctl start biometric
```

Check it started correctly:

```bash
sudo systemctl status biometric
```

View live logs:

```bash
journalctl -u biometric -f
```

---

## 9. Install Cloudflare Tunnel

### 9.1 Install cloudflared (32-bit ARM build)

```bash
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm
chmod +x cloudflared-linux-arm
sudo mv cloudflared-linux-arm /usr/local/bin/cloudflared
cloudflared --version
```

### 9.2 Authenticate and Create Tunnel

```bash
cloudflared tunnel login
```

A browser link will print — open it on another machine and authorize your domain.

```bash
cloudflared tunnel create biometric
```

Note the **Tunnel ID** printed (a UUID like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

### 9.3 Create Tunnel Config

```bash
sudo mkdir -p /etc/cloudflared
```

```bash
sudo tee /etc/cloudflared/config.yml <<EOF
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /root/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: biometric.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF
```

Replace `<YOUR_TUNNEL_ID>` and `biometric.yourdomain.com` with your actual values.

### 9.4 Add DNS Record

```bash
cloudflared tunnel route dns biometric biometric.yourdomain.com
```

### 9.5 Install and Start cloudflared Service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared
```

### 9.6 Set Access Policy (Cloudflare Dashboard)

1. Go to **Zero Trust → Access → Applications → Add an application**
2. Choose **Self-hosted**
3. Set the domain to `biometric.yourdomain.com`
4. Add an **Allow** policy — e.g., email OTP for your email address
5. Save

After this, visiting `https://biometric.yourdomain.com` will require authentication before reaching the API.

---

## 10. Verify Everything End-to-End

```bash
# Service health
sudo systemctl status biometric
sudo systemctl status cloudflared

# Local API check
curl http://127.0.0.1:8000/status

# Remote API check (after Cloudflare auth)
curl https://biometric.yourdomain.com/status

# Latest events
curl "https://biometric.yourdomain.com/events?limit=5"

# Events by user
curl "https://biometric.yourdomain.com/events?user_id=123"

# Events from a date
curl "https://biometric.yourdomain.com/events?from=2026-04-10"
```

---

## 11. Ongoing Maintenance

### View logs

```bash
# Live service log
journalctl -u biometric -f

# Rotating file log
tail -f /opt/biometric/logs/server.log
```

### Check database size

```bash
du -sh /opt/biometric/data/events.db
sqlite3 /opt/biometric/data/events.db "SELECT COUNT(*) FROM events;"
```

### Restart after config change

```bash
sudo systemctl restart biometric
```

### Update code

```bash
sudo systemctl stop biometric
sudo cp new_files /opt/biometric/
sudo chown -R biometric:biometric /opt/biometric
sudo systemctl start biometric
```

### Monitor memory usage

```bash
ps aux | grep python
# Expect ~30-50MB RSS total
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Connected` then immediately `disconnected` | Wrong IP or device off | Check device IP in menu: Comm → Ethernet |
| `ZKNetworkError` in logs | Firewall or VLAN blocking port 4370 | Verify network path, check `ping <device_ip>` from Pi |
| No events after punching | Device in wrong mode | Ensure device is not in "enrollment" mode |
| API returns 502 via Cloudflare | `biometric` service not running | `sudo systemctl start biometric` |
| `cloudflared` fails to start | Wrong tunnel ID or missing credentials file | Re-run `cloudflared tunnel login` and recreate config |
| SD card filling up | Logs or DB growing | Check `du -sh /opt/biometric/data /opt/biometric/logs` |
