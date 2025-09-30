# Protocols/PAR/run_par.py
from Simulator.engine import Engine
from Simulator.config import SimConfig
from Events.api import bind, wait_for_event, from_physical_layer
from Utils.types import FrameKind, EventType
from Protocols.PAR.par import ParSender, ParReceiver

def run_par_single_thread(total_events=4000):
    # Config canal/tiempos (ajusta a gusto)
    cfg = SimConfig(
        delay=0.02, jitter=0.01,
        loss_prob=0.10, corrupt_prob=0.02,
        data_timeout=0.25, ack_timeout=0.08,  # ack_timeout no se usa en PAR
        max_seq=1, nr_bufs=1                  # PAR = bit alternante, ventana 1
    )
    env = Engine(cfg)
    bind(env)

    S = ParSender()
    R = ParReceiver()

    # Activa la capa de red (ParSender la desactiva cuando tiene DATA en vuelo)
    from Events.api import enable_network_layer
    enable_network_layer()

    events_processed = 0
    while events_processed < total_events:
        ev, payload = wait_for_event()

        if ev == EventType.FRAME_ARRIVAL:
            f = from_physical_layer(payload)
            # Si el engine indica corrupción con None, seguimos
            if not f:
                events_processed += 1
                continue
            # DATA -> receptor, ACK -> emisor
            if f.kind == FrameKind.DATA:
                R.on_event(ev, f)
            else:
                S.on_event(ev, f)

        elif ev in (EventType.NETWORK_LAYER_READY, EventType.TIMEOUT):
            S.on_event(ev, payload)

        # otros eventos se ignoran (o agrégalos si los usas)
        events_processed += 1

    # Resumen opcional
    snap = env.snapshot()
    print(f"t_sim={snap['time']:.3f}s  TX={len(snap['tx'])}  RX={len(snap['rx'])}")

if __name__ == "__main__":
    run_par_single_thread()
