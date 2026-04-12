import os
import warnings
import multiprocessing

from . import exceptions


def _normalize_groups(val):
    """Return val as a list of group name strings.

    Accepts a list of strings or a bare scalar string (single group).
    Raises TypeError for any other type so mis-typed YAML is caught early.
    """
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return val
    raise TypeError(f"'groups' must be a string or list of strings, got {type(val).__name__!r}")

def get_parallelism():
    return int(os.getenv('N_THREADS', multiprocessing.cpu_count()))


def resolve_group(group, rotation_config):

    rots = []
    for r, params in rotation_config.items():
        if params and group in _normalize_groups(params.get('groups')):
            rots.append(r)

    if not rots:
        raise exceptions.NameNotFound(
            f"Group {group} resolved to empty.", name=group)

    return rots


def accumulate_prior_counts(rotations, resident_config):

    # options for 'history' are:
    # 1) history: [Tutorial, Tutorial, Ortho, ..., Cardiac]

    prior_counts = {r: 0 for r in resident_config.keys()}

    for rotation in rotations:
        for resident, params in resident_config.items():
            if params and 'history' in params:
                for rot in params['history']:
                    if rot == rotation:
                        prior_counts[resident] += 1

    return prior_counts
