# TakshviTrade — Complete Setup Guide

## Step 1 — Create .env file (YOUR SECRET FILE)
```
Create a file called `.env` inside the `backend/` folder.
Copy from `.env.example` and fill in your real values:
TWILIO_SID=your_sid_here
TWILIO_TOKEN=YOUR_NEW_TOKEN_AFTER_REGENERATING
TWILIO_FROM=whatsapp:+14155238886
TWILIO_TO=whatsapp:+91XXXXXXXXXX
SECRET_KEY=your_secret_key_here
ENVIRONMENT=development
```

⚠️ IMPORTANT: Regenerate your Auth Token on Twilio first!
Your old token was shared publicly. Go to console.twilio.com → regenerate.

---

## Step 2 — Activate WhatsApp Sandbox on your phone

1. Go to console.twilio.com
2. Click Messaging → Try it out → Send a WhatsApp message
3. Note the sandbox number (+14155238886) and join code
4. On your phone: WhatsApp the join code to +14155238886
5. You get a confirmation reply → sandbox is active

---

## Step 3 — Install and test locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Open browser: http://localhost:8000
You should see: {"status": "ok", "platform": "Takshvi Trade"}

Test WhatsApp:
http://localhost:8000/api/signals/quick?capital=50000

---

## Step 4 — Push to GitHub

```bash
# In the takshvitrade folder
git init
git add .
git commit -m "TakshviTrade v1 — initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/takshvitrade.git
git push -u origin main
```

Create the repo on github.com first (new repo → name: takshvitrade)

---

## Step 5 — Deploy to Render (free hosting)

1. Go to render.com → New → Web Service
2. Connect your GitHub account
3. Select the takshvitrade repo
4. Settings:
   - Root directory: backend
   - Build command: pip install -r requirements.txt
   - Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
5. Add environment variables (same as your .env file)
6. Click Deploy

Your API will be live at: https://takshvitrade-api.onrender.com

---

## Step 6 — Test live API

```
https://takshvitrade-api.onrender.com/
https://takshvitrade-api.onrender.com/api/signals/quick?capital=50000
https://takshvitrade-api.onrender.com/api/signals/capacity?capital=50000
```

---

## Daily Usage (Evening after 3:30 PM)

Send WhatsApp alerts with scan results:
POST https://takshvitrade-api.onrender.com/api/signals/alert/send
Body: {"capital": 50000, "send_whatsapp": true}

Or use the quick URL:
https://takshvitrade-api.onrender.com/api/signals/quick?capital=50000
