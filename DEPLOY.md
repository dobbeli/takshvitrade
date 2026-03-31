# Takshvi Trade — Full Stack Deployment Guide
# Domains: takshvitrade.com | takshvitrade.in

## PROJECT STRUCTURE
```
takshvitrade/
├── backend/
│   ├── main.py                  ← FastAPI app entry point
│   ├── requirements.txt         ← pip install -r requirements.txt
│   ├── scanner/
│   │   └── engine.py            ← Your Block 4-7 scanner code
│   └── routers/
│       ├── signals.py           ← /api/signals/* endpoints
│       ├── market.py            ← /api/market/* endpoints
│       ├── auth.py              ← /api/auth/* + JWT
│       └── news.py              ← /api/news/* (your get_eod_news)
└── frontend/
    └── index.html               ← Complete website + dashboard
```

---

## STEP 1 — BACKEND DEPLOYMENT (Free on Render.com)

1. Create account at render.com
2. New → Web Service → Connect your GitHub repo
3. Settings:
   - Build Command:  pip install -r requirements.txt
   - Start Command:  uvicorn main:app --host 0.0.0.0 --port 8000
   - Root Directory: backend/
4. Environment Variables (add in Render dashboard):
   - JWT_SECRET=your-random-secret-string-here
5. Your API will be live at: https://api.takshvitrade.com

Custom domain setup:
- In Render: Settings → Custom Domain → api.takshvitrade.com
- In your DNS (GoDaddy/Cloudflare):
  CNAME  api  →  your-render-app.onrender.com

---

## STEP 2 — FRONTEND DEPLOYMENT (Free on Vercel/Netlify)

Option A — Vercel (Recommended):
1. vercel.com → New Project → Upload frontend/ folder
2. Settings → Domains → Add takshvitrade.com and takshvitrade.in
3. DNS Settings (at your registrar):
   A     @    →  76.76.21.21
   CNAME www  →  cname.vercel-dns.com

Option B — Netlify:
1. netlify.com → New Site → Drag and drop frontend/ folder
2. Site Settings → Domain Management → Add custom domain

---

## STEP 3 — CONNECT FRONTEND TO YOUR API

In index.html, find and replace:
  const API_BASE = 'https://api.takshvitrade.com'

Then update the runScan() function to call your real API:
  const res = await fetch(`${API_BASE}/api/signals/top5`)
  const data = await res.json()

---

## STEP 4 — DATABASE (Free Supabase)

1. supabase.com → New Project
2. Create tables:

   users:    id, email, name, plan, created_at
   signals:  id, stock, score, entry, stop_loss, target, rr, scanned_at
   scans:    id, user_id, results_json, created_at

3. Add to Render environment variables:
   SUPABASE_URL=https://xxx.supabase.co
   SUPABASE_KEY=your-anon-key

---

## STEP 5 — WHATSAPP ALERTS (Twilio — Free Trial)

1. twilio.com → Create account → Get free number
2. Add to Render environment variables:
   TWILIO_SID=your-sid
   TWILIO_TOKEN=your-token
   TWILIO_FROM=whatsapp:+14155238886

3. In scanner/engine.py, add after scan completes:
   from twilio.rest import Client
   client = Client(sid, token)
   client.messages.create(
     body=f"🟢 BUY {stock} @ ₹{entry} | SL ₹{stop} | Target ₹{target}",
     from_='whatsapp:+14155238886',
     to='whatsapp:+91XXXXXXXXXX'
   )

---

## STEP 6 — PAYMENTS (Razorpay)

1. razorpay.com → Create account
2. Get API Key + Secret
3. Add to frontend before </body>:
   <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
4. On "Subscribe" button click:
   var rzp = new Razorpay({
     key: 'rzp_live_XXXXXXXXXX',
     amount: 29900,  // ₹299 in paise
     currency: 'INR',
     name: 'Takshvi Trade',
     description: 'Basic Plan — Monthly',
     handler: function(response) {
       // Call your backend to upgrade user plan
     }
   });
   rzp.open();

---

## LIVE API ENDPOINTS

Once deployed, your API will support:

GET  /api/signals/scan         → Full NIFTY50 scan (~15 min)
GET  /api/signals/top5         → Top 5 signals fast
GET  /api/signals/stock/TCS    → Single stock signal
GET  /api/signals/groww-sheet  → Groww-formatted orders
GET  /api/market/status        → NIFTY health check
GET  /api/market/nifty         → Current NIFTY price+RSI
POST /api/auth/register        → Create account
POST /api/auth/login           → Get JWT token
GET  /api/auth/me              → Current user + plan
GET  /api/auth/plans           → All subscription plans
GET  /api/news/eod             → News + sentiment

---

## COST BREAKDOWN (Month 1-2)

| Service      | Cost    | Notes                    |
|--------------|---------|--------------------------|
| Render.com   | FREE    | 750 hrs/month free       |
| Vercel       | FREE    | Hobby plan unlimited     |
| Supabase     | FREE    | 500MB DB, 50K MAU        |
| Twilio       | FREE    | Trial credits            |
| Domain .com  | ~₹800   | GoDaddy/Namecheap/year   |
| Domain .in   | ~₹600   | Same registrar/year      |
| **Total**    | **~₹1,400/year** | Just domains!  |

---

## QUICK START (local dev)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend — just open in browser
open frontend/index.html

# API docs auto-generated at:
# http://localhost:8000/docs
```
