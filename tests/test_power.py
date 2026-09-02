from chargerwin.power import FakePowerSource, PowerStatus


def test_fake_defaults():
    src = FakePowerSource()
    assert src.status() == PowerStatus(plugged=True, battery_percent=50)


def test_fake_set():
    src = FakePowerSource()
    src.set(plugged=False)
    assert src.status().plugged is False
    assert src.status().battery_percent == 50
    src.set(plugged=True, battery_percent=9)
    assert src.status() == PowerStatus(plugged=True, battery_percent=9)
