# Protocols/SelectiveRepeat/run_selectiveRepeat.py
from Simulator.engine import Engine
from Simulator.config import SimConfig
from Events.api import bind
from Protocols.SelectiveRepeat.selectiveRepeat import run_sr_bidirectional

def main():
    cfg = SimConfig(
        delay=0.02, jitter=0.01,
        loss_prob=0.4, corrupt_prob=0.2,
        data_timeout=0.25, ack_timeout=0.08,
        max_seq=7, nr_bufs=(7+1)//2
    )
    eng = Engine(cfg)
    bind(eng)


    TOTAL_STEPS = 2000
    BLOCK = 100
    done = 0
    while done < TOTAL_STEPS:
        run_sr_bidirectional(steps=BLOCK, max_seq=cfg.max_seq)
        done += BLOCK

    snap = eng.snapshot()
    tx = snap["tx"]
    rx = snap["rx"]
    tx_data = [t for t in tx if t[1] == "DATA"]
    tx_ack  = [t for t in tx if t[1] == "ACK"]

    print(f"Tiempo sim: {snap['time']}")
    print(f"TX total: {len(tx)} DATA: {len(tx_data)} ACK: {len(tx_ack)} | RX: {len(rx)}")


    ok_orden = all(data == f"MSG_{i}" for i, (_, data) in enumerate(rx))
    print("Orden de RX:", "OK" if ok_orden else "X")

    if cfg.loss_prob == 0.0 and cfg.corrupt_prob == 0.0:

        assert ok_orden, "RX fuera de orden en canal perfecto"
        print("Selective Repeat con piggyback (canal perfecto) ✔")
    else:

        eficiencia = (len(rx) / len(tx_data)) if tx_data else 0.0
        retransmisiones_aprox = len(tx_data) - len(rx)
        goodput = (len(rx) / snap["time"]) if snap["time"] > 0 else 0.0
        print(f"Eficiencia (RX/DATA_TX): {eficiencia:.2f}")
        print(f"Retransmisiones aprox.: {retransmisiones_aprox}")
        print(f"Goodput (pkts/seg): {goodput:.2f}")

if __name__ == "__main__":
    main()
