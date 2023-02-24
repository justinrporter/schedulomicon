import os

def get_parallelism():
    return int(os.getenv('N_THREADS', 1))
