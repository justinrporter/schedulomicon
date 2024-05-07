import os
import multiprocessing

def get_parallelism():
    return int(os.getenv('N_THREADS', multiprocessing.cpu_count()))


def resolve_group(group, rotation_config):

    rots = [
        r for r, params in rotation_config.items()
        if params and group in params.get('groups', [])
    ]

    return rots


def accumulate_prior_counts(rotation, resident_config):

    # options for 'history' are:
    # 1) history: [Tutorial, Tutorial, Ortho, ..., Cardiac]

    prior_counts = {r: 0 for r in resident_config.keys()}
    for resident, params in resident_config.items():
        if 'history' in params:
            for rot in params['history']:
                if rot == rotation:
                    prior_counts[resident] += 1

    return prior_counts
