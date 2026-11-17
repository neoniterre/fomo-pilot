"""Run: python test_summary.py  (no network). summary.py --cloud with a fake fetch (local fixtures)."""
import io
import json
import subprocess
import sys
import types
from contextlib import redirect_stdout

import summary
from summary import CLOUD_BASE, cloud_block, show_cloud, state_lines, trades_lines

# --- fixtures in the exact formats written by risk.py (state.json, trades.jsonl) ---
STATE = {"capital": 20.42, "day": "2026-11-18", "day_start_capital": 20.0, "daily_pnl": 0.42, "trades_today": 2,
         "halted": False,
         "positions": {"GTA6": {"token": "GTA6", "entry_price": 0.0166, "initial_usd": 1.33, "stop_pct": 12.0,
                                "high": 0.0172, "remaining_frac": 0.6, "tp1_done": True, "tp2_done": False,
                                "opened_at": "2026-11-18T09:12:00+00:00", "ref": "solana:4kjru"}}}
TRADES = "\n".join(json.dumps(t) for t in [
    {"mode": "paper", "side": "buy", "token": "GTA6", "usd": 1.33, "theoretical_price": 0.0166, "fill_price": None,
     "slippage_pct": 0.0, "stop_pct": 12.0, "ts": "2026-11-18T09:12:00.123+00:00"},
    {"mode": "paper", "side": "sell", "token": "GTA6", "frac": 0.4, "theoretical_price": 0.0233, "fill_price": None,
     "slippage_pct": 0.0, "pnl_usd": 0.2141, "reason": "TP1 (+40%)", "ts": "2026-11-18T10:40:00+00:00"},
]) + "\n{broken line\n"


def fake(files, raise_for=()):
    """files: {name: text}; missing name -> 404; name in raise_for -> network error."""
    calls = []

    def fetch(url):
        calls.append(url)
        assert url.startswith(CLOUD_BASE)
        name = url[len(CLOUD_BASE):]
        if name in raise_for:
            raise OSError("getaddrinfo failed")
        return (200, files[name]) if name in files else (404, "")
    fetch.calls = calls
    return fetch


def text(lines):
    return "\n".join(lines)


def test_cloud_url_is_public_data_branch():
    assert CLOUD_BASE == "https://raw.githubusercontent.com/neoniterre/fomo-pilot/data/"


def test_cloud_summary_state_and_trades():
    f = fake({"state.json": json.dumps(STATE), "trades.jsonl": TRADES})
    out = text(cloud_block(f))
    assert "Capital : 20.42 $" in out and "Aujourd'hui : +0.42 $" in out and "Trades du jour : 2" in out
    assert "Position ouverte : GTA6  $0.80" in out                  # 1.33 * 0.6
    assert "PAPER ACHAT  GTA6  $1.33" in out and "PAPER VENTE  GTA6  40%  +0.21 $  (TP1 (+40%))" in out
    assert "Derniers trades (2 sur 2)" in out                        # broken line skipped, no crash
    assert "STOP" not in out
    assert [u[len(CLOUD_BASE):] for u in f.calls] == ["STOP", "state.json", "trades.jsonl"]


def test_cloud_summary_missing_files_and_stop():
    out = text(cloud_block(fake({})))
    assert "Pas encore d'état dans le cloud" in out and "pas encore de trades.jsonl" in out
    out = text(cloud_block(fake({"STOP": "", "state.json": json.dumps(STATE)})))
    assert "Arrêt d'urgence demandé" in out and "Capital : 20.42 $" in out


def test_cloud_summary_never_crashes():
    out = text(cloud_block(fake({}, raise_for=("STOP", "state.json", "trades.jsonl"))))
    assert "Impossible de joindre GitHub" in out and "connexion" in out
    out = text(cloud_block(fake({"state.json": "<html>rate limited</html>"})))
    assert "illisible" in out
    out = text(cloud_block(fake({"state.json": json.dumps({"capital": "x"})})))   # wrong shape
    assert "illisible" in out
    out = text(cloud_block(fake({"state.json": json.dumps([1, 2])})))
    assert "illisible" in out

    def server_error(url):
        return 503, ""
    out = text(cloud_block(server_error))
    assert "GitHub a répondu 503" in out


def test_show_cloud_prints():
    buf = io.StringIO()
    with redirect_stdout(buf):
        show_cloud(types.SimpleNamespace(last=20), fetch=fake({"state.json": json.dumps(STATE)}))
    assert "RÉSUMÉ DU BOT CLOUD" in buf.getvalue() and "Capital : 20.42 $" in buf.getvalue()


def test_local_summary_unchanged():
    assert state_lines(STATE)[0].startswith("Capital : 20.42 $")
    assert trades_lines("") == ["Aucun trade pour l'instant."]


def test_cli_has_cloud_option():
    p = subprocess.run([sys.executable, "summary.py", "--help"], capture_output=True, timeout=30)
    assert p.returncode == 0 and b"--cloud" in p.stdout


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
