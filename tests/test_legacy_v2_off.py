from hyparena.card import verifier


def test_mouse_probes_are_off_when_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(verifier, "analog_probes", lambda card: calls.append(card) or ["probe"])
    monkeypatch.setattr(verifier, "verify_claim", lambda *a, **k: None)

    class Card:
        claims, rejected_alternatives = [], []
    try:
        verifier.verify(None, ["a", "b"], "w", Card(), probes=False, map_fn=lambda f, xs: [f(x) for x in xs])
    except Exception:
        pass                                    # only whether the probes were asked for matters here
    assert calls == []
