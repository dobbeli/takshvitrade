"""
Takshvi Trade — FastAPI Backend
Domain: takshvitrade.com / takshvitrade.in
"""
"""
Takshvi Trade — FastAPI Backend
"""
import sys
import traceback

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from contextlib import asynccontextmanager
    print("✅ FastAPI imported")
except Exception as e:
    print(f"❌ FastAPI import failed: {e}")
    sys.exit(1)

try:
    from routers import signals, market, auth, news
    print("✅ Routers imported")
except Exception as e:
    print(f"❌ Router import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✅ Takshvi Trade API started")
    yield
    print("🛑 Takshvi Trade API stopped")

app = FastAPI(
    title="Takshvi Trade API",
    description="NSE Swing Signal Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,    prefix="/api/auth",    tags=["Auth"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(market.router,  prefix="/api/market",  tags=["Market"])
app.include_router(news.router,    prefix="/api/news",    tags=["News"])

@app.get("/")
def root():
    return {"status": "ok", "platform": "Takshvi Trade", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}