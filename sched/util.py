import os
import multiprocessing

def get_parallelism():
    return int(os.getenv('N_THREADS', multiprocessing.cpu_count()))
