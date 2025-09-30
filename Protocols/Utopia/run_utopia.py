from Simulator.engine import Engine
from Events.api import bind
from Protocols.Utopia.utopia import sender_utopia, receive_utopia

eng = Engine(); bind(eng)

for _ in range(2000):
    sender_utopia(steps=1)
    receive_utopia(steps=1)

snap = eng.snapshot()
print("Eventos:", snap["events"])
print("TX:", snap["tx"])
print("RX:", snap["rx"])

# --- Resumen simple ---
tx_total = len(snap["tx"])
rx_total = len(snap["rx"])
print(f"Resumen: salieron={tx_total}, entregó={rx_total}")


