"""Run: python test_pilot.py  (no network, no key, no Chrome). Fake browser objects only."""
import asyncio
import types

import pilot
from pilot import FomoPilot

pilot.logger.disabled = True   # never write fake "Chrome fermé" lines into the real pilot.log


class FakePage:
    def __init__(self, closed=False):
        self.closed, self.visited = closed, []

    def is_closed(self):
        return self.closed

    async def goto(self, url, **kw):
        self.visited.append(url)


class FakeBrowser:
    def __init__(self, connected=True, page=None):
        self.connected = connected
        self.contexts = [types.SimpleNamespace(pages=[page or FakePage()])]

    def is_connected(self):
        return self.connected


class FakeChromium:
    """connect_over_cdp fails `fails` times, then returns a fresh browser."""

    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    async def connect_over_cdp(self, url):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("ECONNREFUSED 127.0.0.1:9222")
        return FakeBrowser()


def bare_pilot(reconnect_min=30.0, auto=False):
    """FomoPilot without __init__ (no provider, no state file, no network)."""
    fp = object.__new__(FomoPilot)
    fp.args = types.SimpleNamespace(reconnect_min=reconnect_min, auto=auto)
    fp.running, fp.browser, fp.page, fp.target = True, None, None, {"symbol": "OLD"}
    from notify import Notifier
    fp.notifier = Notifier("")                              # disabled: no network
    return fp


async def _no_sleep(_s):
    return None


def test_browser_dead():
    fp = bare_pilot()
    fp.browser, fp.page = FakeBrowser(), FakePage()
    assert fp._browser_dead() is False
    fp.browser = FakeBrowser(connected=False)
    assert fp._browser_dead() is True                       # Chrome closed
    fp.browser, fp.page = FakeBrowser(), FakePage(closed=True)
    assert fp._browser_dead() is True                       # tab closed

    class Broken(FakeBrowser):
        def is_connected(self):
            raise RuntimeError("target closed")
    fp.browser, fp.page = Broken(), FakePage()
    assert fp._browser_dead() is True                       # any error = treat as dead


def test_recover_reconnects_after_failures():
    real_sleep = pilot.asyncio.sleep
    pilot.asyncio.sleep = _no_sleep                         # skip the 30 s waits
    try:
        fp = bare_pilot()
        chromium = FakeChromium(fails=2)
        ok = asyncio.run(fp._recover(types.SimpleNamespace(chromium=chromium)))
    finally:
        pilot.asyncio.sleep = real_sleep
    assert ok is True and chromium.calls == 3
    assert fp.browser is not None and fp.page.visited == ["https://fomo.family"]
    assert fp.target is None                                # verification restarts from scratch


def test_recover_gives_up():
    fp = bare_pilot(reconnect_min=0)                        # deadline already passed
    chromium = FakeChromium(fails=99)
    assert asyncio.run(fp._recover(types.SimpleNamespace(chromium=chromium))) is False
    assert chromium.calls == 0

    real_sleep = pilot.asyncio.sleep
    pilot.asyncio.sleep = _no_sleep
    try:
        fp = bare_pilot()
        fp.running = False                                  # stop requested -> no retry loop
        assert asyncio.run(fp._recover(types.SimpleNamespace(chromium=FakeChromium(0)))) is False
    finally:
        pilot.asyncio.sleep = real_sleep


class FakeTarget:
    """Playwright locator stand-in: `desc` is what ELEMENT_DESC_JS would return."""

    def __init__(self, desc, log):
        self.desc, self.log, self.first = desc, log, self

    async def count(self):
        return 1

    async def evaluate(self, js, timeout=None):
        return self.desc

    async def click(self, timeout=None):
        self.log.append(("click", self.desc))

    async def fill(self, value, timeout=None):
        self.log.append(("fill", value))


class FakeUiPage:
    def __init__(self, elements):
        self.elements, self.log = elements, []

    def locator(self, selector):
        return FakeTarget(self.elements.get(selector, ""), self.log)

    def get_by_text(self, text, exact=False):
        return FakeTarget(self.elements.get(text, ""), self.log)

    get_by_placeholder = get_by_label = get_by_text


def ui_pilot(page, navigate=True, live=False):
    fp = bare_pilot()
    fp.page, fp.pending, fp.live = page, None, live
    fp.args.navigate = navigate
    return fp


def test_exec_ui_checks_the_real_element():
    page = FakeUiPage({
        "#x1": "Buy now",                       # CSS selector hiding a Buy button
        "div > span.css-3k": "",                # icon with no text
        "Trending": "Trending /trending",
        "Search": "Search tokens",
    })
    fp = ui_pilot(page)
    run = lambda ui: asyncio.run(fp.exec_ui(ui))
    assert run({"action": "click", "selector": "#x1"}) is False
    assert run({"action": "click", "selector": "div > span.css-3k"}) is False
    assert page.log == []                                   # nothing was clicked
    assert run({"action": "click", "selector": "Trending"}) is True
    assert run({"action": "type", "selector": "Search", "value": "GTA6"}) is True
    assert page.log == [("click", "Trending /trending"), ("fill", "GTA6")]


def test_exec_ui_paper_without_navigate_never_clicks():
    page = FakeUiPage({"Trending": "Trending"})
    fp = ui_pilot(page, navigate=False)
    assert asyncio.run(fp.exec_ui({"action": "click", "selector": "Trending"})) is False
    assert page.log == []


class FakeListPage:
    """fomo list tab: the table header shows first, rows a bit later. No wait_for_function on purpose:
    fomo's CSP blocks it (17/11/2026), _read_list must poll with evaluate()."""

    def __init__(self, texts):
        self.texts, self.gotos = list(texts), 0
        self.url = "https://fomo.family/top-movers"

    async def goto(self, url, **kw):
        self.gotos += 1

    async def evaluate(self, js):
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]

    async def bring_to_front(self):
        pass


def test_read_list_waits_for_rows_without_wait_for_function():
    from test_scanner import TOP_MOVERS_TABLE
    header_only = TOP_MOVERS_TABLE.split("1\t")[0]          # "Position in this view" but no rows yet
    real_sleep = pilot.asyncio.sleep
    pilot.asyncio.sleep = _no_sleep
    try:
        fp = bare_pilot()
        page = FakeListPage(["", header_only, header_only, TOP_MOVERS_TABLE])
        text = asyncio.run(fp._read_list(page, "top-movers"))
    finally:
        pilot.asyncio.sleep = real_sleep
    assert text == TOP_MOVERS_TABLE and page.gotos == 1      # waited for the rows, no reload needed


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok  ", k)
    print(f"\n{n} tests passed")
