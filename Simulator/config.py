
from dataclasses import dataclass

@dataclass
class SimConfig:
    delay: float = 0.0            # retardo medio del canal (Utopía: 0)
    jitter: float = 0.0           # +/- aleatorio (opcional)
    loss_prob: float = 0.0        # prob. de pérdida (Utopía/PAR off, GBN/SR on)
    corrupt_prob: float = 0.0     # prob. de corrupción (para CKSUM_ERR)
    ack_timeout: float = 0.15     # temporizador para ACK diferido
    data_timeout: float = 0.5     # temporizador por trama en PAR/GBN/SR
    max_seq: int = 7              # 1, 3, 7, 15... (2^n - 1)
    nr_bufs: int = (7 + 1)//2     # buffers de SR: (max_seq+1)/2 (recalcula si cambias max_seq)