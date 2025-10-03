
def inc(k, max_seq):
    if k >= max_seq:
        return 0
    else:
        return k + 1

def between(a: int, b: int, c: int) -> bool:

    if a <= c:
        return a <= b < c
    else:
        # ventana envuelve: [a..M-1] U [0..c-1]
        return b >= a or b < c
