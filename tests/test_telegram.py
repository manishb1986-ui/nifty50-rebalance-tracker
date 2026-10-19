from nifty50_tracker import telegram_bot


def test_only_authorised_chat_is_answered(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    sent, acked = [], []
    updates = [
        {"update_id": 5, "message": {"chat": {"id": 111}, "text": "/help"}},
        {"update_id": 6, "message": {"chat": {"id": 999}, "text": "/run"}},
    ]

    def fake_call(method, **params):
        if method == "getUpdates" and "offset" in params:
            acked.append(params["offset"])
            return {"result": []}
        return {"result": updates}

    monkeypatch.setattr(telegram_bot, "_call", fake_call)
    monkeypatch.setattr(telegram_bot, "send", lambda chat, text: sent.append((chat, text)))
    telegram_bot.poll()
    assert [c for c, _ in sent] == ["111"]
    assert "/status" in sent[0][1]
    assert acked == [7]
