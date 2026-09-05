import time

def log_time(f):
    def w(*a, **k):
        s = time.perf_counter()
        r = f(*a, **k)
        print(f"'{f.__name__}' took {time.perf_counter() - s:.4f}s")
        return r
    return w