import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from libs.db import create_tables
from libs.oss_client import OssClient
from libs.redis_client import RedisClient
from libs.settings import get_settings
from service.api.files import router
from service.handler import VideoHandler, PdfHandler
from service.ocr import create_ocr_adapter
from service.worker import Consumer, ParseWorker

logger = logging.getLogger(__name__)


def build_worker():
    settings = get_settings()
    return ParseWorker(
        settings=settings,
        oss_client=OssClient(settings),
        ocr_adapter=create_ocr_adapter(settings),
        video_handler=VideoHandler(settings),
        pdf_handler=PdfHandler(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await asyncio.to_thread(create_tables)
    worker = await asyncio.to_thread(build_worker)
    redis_client = RedisClient(settings)
    consumer = Consumer(settings=settings, redis_client=redis_client, worker=worker)
    await asyncio.to_thread(consumer.start)
    app.state.consumer = consumer
    app.state.worker = worker
    logger.info("application startup complete")
    yield
    await asyncio.to_thread(consumer.stop)
    logger.info("application shutdown complete")


app = FastAPI(title="llm-construct-question", lifespan=lifespan)
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    uvicorn.run("service.main:app", host=settings.server.host, port=settings.server.port, reload=True)
