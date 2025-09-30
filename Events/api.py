
_env = None

def bind(env):
    global _env
    _env = env

def wait_for_event():
    return _env.wait_for_event()

def from_network_layer():
    return _env.from_network_layer()

def to_network_layer(p):
    return _env.to_network_layer(p)

def from_physical_layer(payload):
    return _env.from_physical_layer(payload)

def to_physical_layer(f):
    return _env.to_physical_layer(f)

def start_timer(seq):
    return _env.start_timer(seq)

def stop_timer(seq):
    return _env.stop_timer(seq)

def start_ack_timer():
    return _env.start_ack_timer()

def stop_ack_timer():
    return _env.stop_ack_timer()

def enable_network_layer():
    return _env.enable_network_layer()

def disable_network_layer():
    return _env.disable_network_layer()