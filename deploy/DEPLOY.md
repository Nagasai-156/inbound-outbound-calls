# Diigoo Voice Worker — EC2 (Mumbai) Deploy Guide

Goal: run the voice worker + control API on an AWS EC2 instance in
**ap-south-1 (Mumbai)** — co-located with Bedrock for low, *consistent*
latency (kills the home-WiFi jitter / dead-air spikes).

What runs on the box: **worker + FastAPI control API + Redis**.
What stays in the cloud: LiveKit SFU, Sarvam STT/TTS, Bedrock LLM,
Supabase DB. (No GPU needed — the heavy AI is all API calls.)

---

## 0. Prerequisite — put the code in git (one time)

The project isn't a git repo yet. On your laptop:

```bash
cd "d:/diigoo/ai calls"
git init
printf "\n.venv/\n__pycache__/\n*.log\n*.log.*\nnode_modules/\n.next/\n" >> .gitignore
# make sure .env is gitignored (it already is) — NEVER commit secrets
git add -A && git commit -m "Initial deploy snapshot"
# create a PRIVATE GitHub repo, then:
git remote add origin git@github.com:<you>/diigoo.git
git push -u origin main
```

---

## 1. Launch the EC2 instance (AWS Console)

- **Region:** Asia Pacific (Mumbai) `ap-south-1`  ← must match Bedrock
- **AMI:** Ubuntu Server 24.04 LTS
- **Type:** `t3.large` (2 vCPU / 8 GB) to start — `t3.xlarge` for real load
- **Key pair:** create/download one for SSH
- **Storage:** 20 GB gp3
- **Security group (inbound):**
  - SSH (22) — your IP only
  - (Nothing else needed — worker/API are outbound + loopback)
- **IAM role (recommended):** attach a role with Bedrock invoke
  permission so you can drop the bearer-token key later.

SSH in:
```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

## 2. Get the code + run setup

```bash
git clone git@github.com:<you>/diigoo.git ~/diigoo   # or scp the folder
cd ~/diigoo
bash deploy/setup.sh        # installs python, redis, ffmpeg, deps (~few min)
```

## 3. Copy your .env to the server

From your **laptop** (new terminal):
```bash
scp -i your-key.pem "d:/diigoo/ai calls/.env" ubuntu@<EC2_PUBLIC_IP>:~/diigoo/.env
```
Then on the server, point Redis to local:
```bash
# in ~/diigoo/.env make sure:  REDIS_URL=redis://localhost:6379/0
```

## 4. Install + start the services

```bash
cd ~/diigoo
bash deploy/install_services.sh
```
Healthy = you see **`registered worker`** in the logs:
```bash
tail -f ~/diigoo/worker.err.log
```

## 5. Make a test call

Dial through your normal outbound flow. Watch the logs — latency should
be steady (~300 ms first sound, ~1 s answer) with **no 7–20 s spikes**.

---

## Day-to-day

- **Config changes** (scripts, model, voice via /settings dashboard):
  live on next call — **no deploy needed**.
- **Code changes:** push to git, then on the box:
  ```bash
  bash deploy/deploy.sh        # git pull + deps + restart (~15s)
  ```
- **Logs:** `journalctl -u diigoo-worker -f`  or  `tail -f worker.err.log`
- **Restart:** `sudo systemctl restart diigoo-worker`
- **Uptime alert (do this!):** point a free monitor (Healthchecks.io /
  UptimeRobot) at a heartbeat so you're paged the instant the worker
  dies — the cure for silent dead-air.

## Notes
- A worker restart drops in-flight calls (~15 s). Deploy in low traffic;
  at scale run 2 workers for rolling, zero-downtime restarts.
- The FastAPI control API binds 127.0.0.1. If the dashboard runs off-box,
  put it behind a reverse proxy + auth — don't bind 0.0.0.0 raw.
