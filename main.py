from fastapi import FastAPI
from routers.redis_router import router as redis_router
from routers.postgres_router import router as postgres_router

app = FastAPI(title="DataService API", version="1.0.0")

app.include_router(redis_router, prefix="/api/v1")
app.include_router(postgres_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {"status": "ok"}
