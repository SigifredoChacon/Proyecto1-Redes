
def inc(k, max_seq):
    if k >= max_seq:
        return 0
    else:
        return k + 1

def between(a, b, c):
    if (((a <= b) and (b < c)) or ((c < a) and (a <= b)) or ((b < c) and (c < a))):
        return True
    else:
        return False
