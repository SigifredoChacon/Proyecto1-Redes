from dataclasses import dataclass

@dataclass
class SimConfig:
    delay: float = 0.0
    jitter: float = 0.0           # variacion de delay
    loss_prob: float = 0.0        # prob. de pérdida
    corrupt_prob: float = 0.0     # prob. de corrupción (para CKSUM_ERR)
    ack_timeout: float = 0.15     # temporizador para piggybacking
    data_timeout: float = 0.5     # temporizador por frame en PAR/GBN/SR
    max_seq: int = 7
    nr_bufs: int = (7 + 1)//2
    ready_on_enable: bool = False
    ready_delay: float = 0.005