# Motor thrust curves — ideal trajectory simulation

`placeholder_motor.csv` is **fake data**, only present so the "Run Simulation"
button on the Map & Tracking tab has something runnable out of the box. It
produces a plausible-looking ~2 second burn, nothing more — do not use it to
predict a real flight.

## Format

Two columns, no header: `time_s,thrust_N`.

```
0.0,0
0.05,180
...
2.0,0
```

This is RocketPy's plain CSV thrust-source format. If your motor manufacturer
publishes a `.eng` or `.rse` file, convert it to this two-column form (time
from ignition in seconds, thrust in Newtons) and drop it in this folder.

## Wiring in a real motor

1. Add the CSV here (or anywhere — the path is configurable).
2. Update `motor.thrust_source` in `config/rocket_config.json` to point at it.
3. Update the rest of `motor.*` in the same file (dry mass, grain geometry,
   nozzle/throat radius, burn time) to match the real motor's datasheet —
   these values are load-bearing for RocketPy's mass/thrust model, not just
   the thrust curve.
