import pandas as pd
import random

data = pd.read_csv('./inputs/rotation-pin.csv')
pins = data.rename(columns={'Unnamed: 0':'resident'})

residents = list(pins['resident'])
residents = random.sample(residents,len(residents))

pins = pins.set_index('resident')
tutorial_blocks = ['Block 21','Block 22','Block 23','Block 24','Block 25','Block 26','Block 27']

conflicts = []
no_conflicts = []

for res in residents:
    if pd.isnull(pins.loc[[res],tutorial_blocks]).values.all():
        no_conflicts.append(res)
    else: 
        conflicts.append(res)

group_counts = [0,0,0,0]

# Residents with conflicts - randomly assign one of the tutorial blocks that they can get. 
# Residents without conflicts - fill in the rest of the tutorial blocks evenly (list has been randomized)

for x, res in enumerate(residents):
    if res in conflicts:
        if pd.isnull(pins.loc[[res],tutorial_blocks[2:]]).values.all():
            group = random.choice([1,2,3])
        elif pd.isnull(pins.loc[[res],tutorial_blocks[4:]]).values.all():
            group = random.choice([2,3])
        else: 
            group = 3
    else: 
        group = group_counts.index(min(group_counts))

    group_counts[group] += 1

    if group == 0: 
        pins.loc[[res],tutorial_blocks] = ['Pre-Tutorial', 'Tutorial 1', 'Tutorial 2', 'Anesthesia CBY', 'Anesthesia CBY', 'Anesthesia CBY', 'Anesthesia CBY']
    elif group == 1:
        pins.loc[[res],tutorial_blocks[2:]] = ['Pre-Tutorial', 'Tutorial 1', 'Tutorial 2', 'Anesthesia CBY', 'Anesthesia CBY']
    elif group == 2:
        pins.loc[[res],tutorial_blocks[4:]] = ['Pre-Tutorial', 'Tutorial 1', 'Tutorial 2']
    else: pins.loc[[res],tutorial_blocks[6:]] = ['Pre-Tutorial']

pins.to_csv('./inputs/rotation-pin-tutorial.csv')