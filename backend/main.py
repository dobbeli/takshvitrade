"""
Takshvi Trade — FastAPI Backend
Domain: takshvitrade.com / takshvitrade.in
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from routers import signals, market, auth, news
import asyncio

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
    allow_origins=[
        "https://takshvitrade.com",
        "https://takshvitrade.in",
        "https://www.takshvitrade.com",
        "http://localhost:3000",   # dev
    ],
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
