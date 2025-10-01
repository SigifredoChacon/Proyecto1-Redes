# Protocols/StopAndWait/stop_and_wait.py
from __future__ import annotations
from Utils.types import Frame, FrameKind, EventType, Packet
from Events.api import (
    wait_for_event, from_network_layer, to_physical_layer, from_physical_layer,
    to_network_layer, enable_network_layer, disable_network_layer,
    start_timer, stop_timer,
)

# -------------------------
# Stop-and-Wait (ABP clásico)
# -------------------------
# - Unidireccional A -> B
# - DATA sale con seq ∈ {0,1} alternando
# - B responde con ACK puro con ack = seq recibido
# - ReTx por TIMEOUT
#
# Notas:
# - max_seq y nr_bufs deben ser 1 (GUI y run_* ya lo fuerzan)
# - Canal puede tener pérdidas/corrupción; ABP se recupera por timeout
# - info en DATA: "S>MSG_n"; info en ACK: "ACK:B" (para la GUI)

# --- Estado del emisor (se mantiene entre llamadas reentrantes) ---
_next_to_send = 0          # bit 0/1 para el siguiente DATA
_buffer_pkt: Packet | None = None  # último paquete tomado de la "red"
_waiting_ack = False       # True si hay DATA pendiente de ACK

def _build_data_frame(seq_bit: int, pkt: Packet) -> Frame:
    # En ABP unidireccional el campo 'ack' del DATA no es usado; dejamos 0
    return Frame(FrameKind.DATA, seq_bit, 0, Packet(f"S>{pkt.data}"))

def _build_ack_frame(ack_bit: int) -> Frame:
    # ACK puro: seq=0 (no usado), ack=ack_bit para la GUI/lógica del emisor
    return Frame(FrameKind.ACK, 0, ack_bit, Packet("ACK:B"))

def sender_sw(steps: int = 10):
    """Emisor A (reentrante)."""
    global _next_to_send, _buffer_pkt, _waiting_ack

    # Si no estoy esperando ACK, permito tomar un nuevo paquete
    if not _waiting_ack:
        enable_network_layer()
    else:
        disable_network_layer()

    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()

        # 1) La capa de red entrega un nuevo paquete
        if ev == EventType.NETWORK_LAYER_READY and not _waiting_ack:
            # tomo y construyo DATA con el bit actual
            _buffer_pkt = from_network_layer()
            frm = _build_data_frame(_next_to_send, _buffer_pkt)
            to_physical_layer(frm)
            # arranco timer para este seq
            start_timer(_next_to_send)
            _waiting_ack = True
            disable_network_layer()
            processed += 1
            continue

        # 2) Llega un ACK
        if ev == EventType.FRAME_ARRIVAL and _waiting_ack:
            r = from_physical_layer(payload)
            if r and r.kind == FrameKind.ACK:
                # ¿ACK para el bit que espero?
                if int(r.ack) == _next_to_send:
                    # recibido: paro timer, alterno bit y vuelvo a habilitar la red
                    stop_timer(_next_to_send)
                    _next_to_send ^= 1
                    _buffer_pkt = None
                    _waiting_ack = False
                    enable_network_layer()
            processed += 1
            continue

        # 3) TIMEOUT -> retransmito el último DATA
        if ev == EventType.TIMEOUT and _waiting_ack:
            # retransmito el frame actual (_buffer_pkt no debería ser None)
            if _buffer_pkt is not None:
                frm = _build_data_frame(_next_to_send, _buffer_pkt)
                to_physical_layer(frm)
                start_timer(_next_to_send)  # rearma timer
            processed += 1
            continue

        # Otros eventos se ignoran aquí
        processed += 1


# --- Estado del receptor ---
_expected = 0  # bit que espero (0/1)

def receiver_sw(steps: int = 10):
    """Receptor B (reentrante)."""
    global _expected

    processed = 0
    while processed < steps:
        ev, payload = wait_for_event()

        if ev == EventType.FRAME_ARRIVAL:
            r = from_physical_layer(payload)
            if r and r.kind == FrameKind.DATA:
                if int(r.seq) == _expected:
                    # DATA nuevo: entrego a red y alterno esperado
                    to_network_layer(r.info)               # p.ej., "S>MSG_n"
                    ack_bit = _expected
                    _expected ^= 1
                else:
                    # Duplicado: re-ACK del último correcto
                    ack_bit = 1 - _expected

                # Envío ACK puro con el bit correspondiente
                to_physical_layer(_build_ack_frame(ack_bit))

        processed += 1