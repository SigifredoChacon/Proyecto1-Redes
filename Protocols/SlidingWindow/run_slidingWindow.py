# Protocols/Sliding1/run_sw1.py
from Simulator.engine import Engine
from Simulator.config import SimConfig
from Events.api import bind
from Protocols.SlidingWindow.slidingWindow import run_gbn_bidirectional

def main():
    # Ajusta la config a tu gusto
    cfg = SimConfig(
        delay=0.02, jitter=0.01,
        loss_prob=0.00, corrupt_prob=0.02,
        data_timeout=0.25, ack_timeout=0.06,
    )
    eng = Engine(cfg)
    bind(eng)  # IMPORTANTÍSIMO: enlaza la API de eventos al Engine

    # Ventana deslizante de 1 bit (Stop-and-Wait full-duplex con piggyback):
    run_gbn_bidirectional(steps=5000, max_seq=1)

    # (Opcional) imprime métricas si tu Engine las expone así:
    try:
        print(f"t_sim={eng.now:.3f}s  TX={len(eng.logs_transmit)}  RX={len(eng.logs_receive)}")
    except Exception:
        pass

if __name__ == "__main__":
    main()