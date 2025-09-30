# Protocols/GoBackN/run_go_back_n.py
from Simulator.engine import Engine
from Simulator.config import SimConfig
from Events.api import bind
from Protocols.Go_back_n.Go_back_n  import run_gbn_bidirectional

def main():
    cfg = SimConfig(
        delay=0.02, jitter=0.01,
        loss_prob=0.4, corrupt_prob=0.2,
        data_timeout=0.25, ack_timeout=0.08,
        max_seq=7, nr_bufs=(7+1)//2
    )
    eng = Engine(cfg)
    bind(eng)


    TOTAL_STEPS = 4000
    BLOCK = 200
    done = 0
    while done < TOTAL_STEPS:
        run_gbn_bidirectional(steps=BLOCK, max_seq=cfg.max_seq)
        done += BLOCK

    snap = eng.snapshot()
    tx = snap["tx"]
    rx = snap["rx"]

    tx_data = [t for t in tx if t[1] == "DATA"]
    tx_ack  = [t for t in tx if t[1] == "ACK"]

    print(f"Tiempo sim: {snap['time']:.2f}")
    print(f"TX total: {len(tx)} DATA: {len(tx_data)} ACK: {len(tx_ack)} | RX: {len(rx)}")


    rxA = [data for _, data in rx if data.startswith("A>")]
    rxB = [data for _, data in rx if data.startswith("B>")]

    def nums(lst):
        out = []
        for m in lst:
            try:
                out.append(int(m.split(">MSG_")[1]))
            except Exception:
                pass
        return out

    numsA = nums(rxA)
    numsB = nums(rxB)
    okA = (numsA == sorted(numsA)) and (len(numsA) == len(set(numsA)))
    okB = (numsB == sorted(numsB)) and (len(numsB) == len(set(numsB)))
    print("Orden por flujo:", f"A={'OK' if okA else 'X'}", f"B={'OK' if okB else 'X'}")


    eficiencia = len(rx) / len(tx_data) if tx_data else 0.0
    goodput = len(rx) / snap["time"] if snap["time"] > 0 else 0.0
    print(f"Eficiencia (RX/DATA_TX): {eficiencia:.2f} | Goodput: {goodput:.2f} pkts/s")

if __name__ == "__main__":
    main()
