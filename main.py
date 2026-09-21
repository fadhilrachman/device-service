import logging
import threading

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from api import config as config_api
from api import device as device_api
from api import payment, session, sync as sync_api, templates, voucher
from config import SYNC_INTERVAL_SECONDS, SYNC_ON_STARTUP
from database import init_db
from lib.helper import BadRequestError, bad_request_exception_handler
from sync import engine

load_dotenv()
logging.basicConfig(level=logging.INFO)


def _startup_sync() -> None:
    """Best-effort first sync; never block app readiness on remote latency."""
    try:
        engine.run_once()
    except Exception:
        logging.exception("startup sync failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if SYNC_ON_STARTUP:
        threading.Thread(target=_startup_sync, name="startup-sync", daemon=True).start()
    engine.start(SYNC_INTERVAL_SECONDS)
    yield
    engine.stop()


app = FastAPI(title="Our Lil Photobooth Device Service", lifespan=lifespan)

app.add_exception_handler(BadRequestError, bad_request_exception_handler)

app.include_router(config_api.router)
app.include_router(device_api.router)
app.include_router(session.router)
app.include_router(voucher.router)
app.include_router(payment.router)
app.include_router(sync_api.router)
app.include_router(templates.router)


@app.get("/")
def root():
    return {"message": "Our Lil Photobooth Device Service is running"}