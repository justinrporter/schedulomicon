# Running it

```bash
python solver.py --config big-pref-separate.yml --results 'results/real-rankings-window-%05d.npz' -p 23 --objective rank_sum_objective --coverage-min hard-min.csv --coverage-max hard-max.csv --rotation-pins rotation-pin.csv --rankings rankings.csv
```

