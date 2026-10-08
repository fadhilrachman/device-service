import logging

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.security import HTTPBearer

from api import auth_device as auth_device_api
from api import campaigns as campaigns_api
from api import config as config_api
from api import device as device_api
from api import plug as plug_api, session, sync as sync_api, templates, upload as upload_api, voucher, whatsapp as whatsapp_api
from database import init_db
from lib.device_liveness import DeviceLivenessMiddleware
from lib.helper import BadRequestError, bad_request_exception_handler
from lib.protect_token import ProtectTokenMiddleware

load_dotenv()
logging.basicConfig(level=logging.INFO)

# Menambahkan skema security agar tombol Authorize muncul di Swagger UI
security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Our Lil Photobooth Device Service",
    lifespan=lifespan,
    dependencies=[Depends(security)],
)

# Registered before ProtectTokenMiddleware so it runs after it (Starlette
# executes the last-added middleware first) and request.state already holds
# the token claims when liveness is recorded.
app.add_middleware(DeviceLivenessMiddleware)
app.add_middleware(ProtectTokenMiddleware)

app.add_exception_handler(BadRequestError, bad_request_exception_handler)

app.include_router(campaigns_api.router)
app.include_router(config_api.router)
app.include_router(device_api.router)
app.include_router(plug_api.router)
app.include_router(sync_api.router)
app.include_router(session.router, include_in_schema=False)
app.include_router(voucher.router)
app.include_router(templates.router)
app.include_router(whatsapp_api.router)
app.include_router(upload_api.router, include_in_schema=False)
app.include_router(auth_device_api.router)


@app.get("/")
def root():
    return {"message": "Our Lil Photobooth Device Service is running"}
