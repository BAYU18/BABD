# Car game (made by the BABD agents)

A 2D keyboard car game the agents built on the server in an early run, before BABD kept the agents'
work apart from its own code. It used to sit at the root of the BABD repository; it lives here now.

- `index.html`: the game (open it in a browser, or serve this folder).
- `test_car_game.py`: its tests: `python -m unittest test_car_game` in this folder.
- `docs/`: the Architect's design spec.

The first run also made a "hello world" `index.html` with its own tests; the car game replaced that
page, so those tests no longer had anything to test and were removed.

New work goes into projects (`workspace/projects/<id>` or a git repository), never into BABD itself.
To let the agents keep working on this game, copy this folder to `workspace/projects/car-game`, add a
project with the id `car-game` in Team settings, and pick it for the task.
