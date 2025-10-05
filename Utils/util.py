
def inc(k, max_seq):
    if k >= max_seq:
        return 0
    else:
        return k + 1

def between(a, b, c):

    if a <= c:
        return a <= b < c
    else:
        return b >= a or b < c
