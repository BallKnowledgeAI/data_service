from pydantic import BaseModel
from .enums import Half


class RawFrame(BaseModel):
    frame_id: int
    timestamp: float
    data: bytes
    half: Half
