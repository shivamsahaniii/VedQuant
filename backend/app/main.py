from fastapi import FastAPI

from app.api import auth, brokers, connections, market, markets, strategies, trading
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()  # fails fast if required settings are missing
configure_logging("DEBUG" if settings.app_env == "dev" else "INFO")

app = FastAPI(title=f"{settings.app_name} API", version="0.1.0")
app.include_router(auth.router)
app.include_router(strategies.router)
app.include_router(brokers.router)
app.include_router(market.router)
app.include_router(trading.router)
app.include_router(connections.router)
app.include_router(markets.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "trading_mode": settings.trading_mode}
