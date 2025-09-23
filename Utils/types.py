from dataclasses import dataclass
from enum import Enum, auto

MAX_PKT_DEFAULT = 1024  # puedes exponerlo en sim/config.py también

class FrameKind(Enum):
    DATA = auto()
    ACK  = auto()
    NAK  = auto()

class EventType(Enum):
    FRAME_ARRIVAL     = auto()
    CKSUM_ERR         = auto()
    TIMEOUT           = auto()
    ACK_TIMEOUT       = auto()
    NETWORK_LAYER_READY = auto()

@dataclass
class Packet:
    data: str

@dataclass
class Frame:
    kind: FrameKind
    seq: int
    ack: int
    info: Packet