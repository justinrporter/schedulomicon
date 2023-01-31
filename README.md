# Running it

```bash
python solver.py --config big-pref-separate.yml --results 'results/vacation-prefs/post-poll-tough-%05d.npz' -p 23 --objective rank_sum_objective --coverage-min hard-min.csv --coverage-max hard-max.csv --rotation-pins rotation-pin.csv --rankings rankings-no-aps.csv --block-resident-ranking 'Vacation CBY' vacation-prefs-adj.csv --hint result-hint.csv
```

