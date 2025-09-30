# Protocols/StopAndWait/run_stop_and_wait.py
from Simulator.engine import Engine
from Simulator.config import SimConfig
from Events.api import bind
from Protocols.Stop_and_wait.Stop_and_wait import sender_sw, receiver_sw

def main():

    cfg = SimConfig(
        delay=0.02, jitter=0.01,
        loss_prob=0.00, corrupt_prob=0.00,
        data_timeout=0.25, ack_timeout=0.08,
        max_seq=1, nr_bufs=1
    )

    eng = Engine(cfg)
    bind(eng)


    TOTAL_STEPS = 2000
    for _ in range(TOTAL_STEPS):
        sender_sw(steps=1)
        receiver_sw(steps=1)

    snap = eng.snapshot()
    tx = snap["tx"]
    rx = snap["rx"]

    tx_data = [t for t in tx if t[1] == "DATA"]
    tx_ack  = [t for t in tx if t[1] == "ACK"]

    print(f"Tiempo sim: {snap['time']:.2f}")
    print(f"TX total: {len(tx)} DATA: {len(tx_data)} DUMMY/ACK: {len(tx_ack)} | RX: {len(rx)}")


    rxS = [data for _, data in rx if data.startswith("S>")]

    def nums(lst):
        out = []
        for m in lst:
            try:
                out.append(int(m.split(">MSG_")[1]))
            except Exception:
                pass
        return out

    numsS = nums(rxS)
    okS = (numsS == sorted(numsS)) and (len(numsS) == len(set(numsS)))
    print("Orden S->R:", "OK" if okS else "X")


    assert okS, "Stop-and-Wait (P2): RX fuera de orden en canal perfecto"
    assert len(rx) == len(tx_data), f"P2 perfecto: DATA_TX({len(tx_data)}) != RX({len(rx)})"


if __name__ == "__main__":
    main()
