"""Toilet paper, Japan, February-March 2020: a run on the shops set off by a rumour.

This world is a check against something that really happened.

The world is an automaton. 240 households each hold a stock of rolls, use some every
day, and follow a small buying rule (when to buy, how much, how hard to try). Six shops
hold stock and are resupplied every morning. News reaches each household through its own
channel. None of that needs AI.

AI is asked only when a household learns something new (the rumour, an empty shelf, the
official statement, a refilled shelf): it then rewrites that household's buying rule,
in character. Between those moments the automaton runs on its own.

Tick t is the morning of day t. Day 0 is Monday 17 February 2020. Shopping for a day
is carried out at the start of the next tick, so sales figures refer to the day before.
"""
import math
import random

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STORES = 6
NORMAL = {"choice": "normal", "packs": 1, "tries": 1}


def date_text(day):
    d = 17 + day                       # 17 February 2020 is day 0; 2020 is a leap year
    if d <= 29:
        return "%s %d Feb" % (DAYS[day % 7], d)
    d -= 29
    if d <= 31:
        return "%s %d Mar" % (DAYS[day % 7], d)
    return "%s %d Apr" % (DAYS[day % 7], d - 31)


def date_ja(day):
    d = 17 + day
    w = "月火水木金土日"[day % 7]
    if d <= 29:
        return "2 月 %d 日（%s）" % (d, w)
    d -= 29
    if d <= 31:
        return "3 月 %d 日（%s）" % (d, w)
    return "4 月 %d 日（%s）" % (d - 31, w)


def normal_reorder(h):
    return 2 + 2 * h["members"]


def init(params, rng):
    people = params["_data"]["households"]
    homes = []
    for h in people:
        homes.append({
            # a household in its ordinary rhythm holds between its reorder point and one pack above it
            "stock": normal_reorder(h) + (h["start_stock"] - 2) / 14.0 * params["pack_rolls"],
            "reorder": normal_reorder(h), "packs": 1, "tries": 1, "urgency": "normal",
            "aware": False, "saw_empty": False, "statement": False, "saw_refill": False, "failed": 0, "asked": 0,
            "last_ask": -99, "news": [], "bought_extra": False,
        })
    daily_packs = sum(h["members"] for h in people) * params["rolls_per_person_day"] / params["pack_rolls"]
    target = daily_packs * params["store_days"] / STORES
    return {
        "homes": homes, "stores": [target] * STORES, "target": target, "daily_packs": daily_packs,
        "wholesale": daily_packs * params["wholesale_days"],
        "sales": [], "wanted": [], "failed": [], "extra_buyers": [], "ask": [], "delivered": 0.0,
    }


def shelf(state, s):
    r = state["stores"][s] / state["target"] if state["target"] > 0 else 0
    return "empty" if r < 0.06 else ("low" if r < 0.35 else "normal")


def shop(state, params, rng, day):
    """Everyone who wants toilet paper on `day` goes to the shops, in random order."""
    people = params["_data"]["households"]
    sold = failed = extra = wanted = 0
    limit = params["limit_packs"] if day >= params["limit_day"] else 99
    order = list(range(len(people)))
    rng.shuffle(order)
    for i in order:
        h, me = people[i], state["homes"][i]
        usual_trip = (day + h["id"]) % h["shop_gap"] == 0
        goes = usual_trip or me["urgency"] == "today" or (me["urgency"] == "soon" and (day + h["id"]) % 2 == 0)
        if not goes:
            continue
        home_store = h["id"] % STORES
        seen = shelf(state, home_store)
        if seen == "empty" and not me["saw_empty"]:
            me["saw_empty"] = True
            me["news"].append("empty")
        if seen == "normal" and me["saw_empty"] and not me["saw_refill"] and day >= params["extra_supply_day"]:
            me["saw_refill"] = True
            me["news"].append("refill")
        if me["stock"] > me["reorder"]:
            continue
        want = max(1, min(int(me["packs"]), limit))
        wanted += max(1, int(me["packs"]))          # what they came for, before any limit or empty shelf
        got = 0
        for k in range(max(1, int(me["tries"]))):
            s = (home_store + k) % STORES
            take = min(want - got, int(state["stores"][s]))
            if take > 0:
                state["stores"][s] -= take
                got += take
            if got >= want:
                break
        if got > 0:
            me["stock"] += got * params["pack_rolls"]
            sold += got
            if me["reorder"] > normal_reorder(h) + 1:
                extra += 1
                me["bought_extra"] = True
            if me["urgency"] == "today":
                me["urgency"] = "soon"          # the special trip is done
        else:
            failed += 1
            me["failed"] += 1
            if not me["saw_empty"]:
                me["saw_empty"] = True
                me["news"].append("empty")
    return sold, failed, extra, wanted


def step(state, params, rng, t):
    events = []
    people = params["_data"]["households"]
    day = t - 1
    # ---- yesterday: shopping, then everyone uses some paper ----
    if day >= 0:
        sold, failed, extra, wanted = shop(state, params, rng, day)
        state["wanted"].append(wanted)
        state["sales"].append(sold)
        state["failed"].append(failed)
        state["extra_buyers"].append(extra)
        for h, me in zip(people, state["homes"]):
            me["stock"] = max(0.0, me["stock"] - h["members"] * params["rolls_per_person_day"])
    # ---- this morning: deliveries (shops order up to their usual level; makers can only send so much) ----
    # Makers produce every day; a wholesaler holds a buffer and can send more than usual until the buffer is gone.
    boost = params["extra_supply_factor"] if params["extra_supply_day"] <= t < params["extra_supply_day"] + params["extra_supply_days"] else 1.0
    state["wholesale"] = min(state["daily_packs"] * params["wholesale_days"], state["wholesale"] + state["daily_packs"] * boost)
    can_send = min(state["wholesale"], state["daily_packs"] * params["max_delivery_factor"])
    need = [max(0.0, state["target"] - s) for s in state["stores"]]
    total_need = sum(need)
    ratio = min(1.0, can_send / total_need) if total_need > 0 else 0.0
    state["delivered"] = total_need * ratio
    state["wholesale"] -= state["delivered"]
    for s in range(STORES):
        state["stores"][s] += need[s] * ratio
    # ---- this morning: what each household hears ----
    exo = random.Random(params["_seed"] * 100003 + t)
    rd, tv, st = int(params["rumour_day"]), int(params["tv_day"]), int(params["statement_day"])
    recent = sum(state["extra_buyers"][-2:]) / len(people) if state["extra_buyers"] else 0.0
    ask = []
    for i, (h, me) in enumerate(zip(people, state["homes"])):
        r = exo.random()
        if not me["aware"]:
            p = 0.0
            if h["info"] == "sns":
                p = 0.35 if t == rd else (0.9 if t > rd else 0.0)
            elif h["info"] == "tv":
                p = 0.8 * params["tv_coverage"] if t >= tv else 0.0
            elif h["info"] == "chat":
                p = (0.35 + 2.0 * recent) if t >= tv else (0.1 if t == rd else 0.0)
            else:
                p = (0.08 + 1.0 * recent) if t >= tv else 0.0
            if r < p:
                me["aware"] = True
                me["news"].append("rumour")
        elif not me["statement"] and t > st:
            p = {"sns": 0.7, "tv": 0.7, "chat": 0.35, "low": 0.1}[h["info"]]
            if r < p:
                me["statement"] = True
                me["news"].append("statement")
        running_low = me["stock"] <= 3 * h["members"] * params["rolls_per_person_day"] * 2 and me["failed"] >= 2 and "low" not in me["news"] and t - me["last_ask"] >= 3
        if running_low:
            me["news"].append("low")
        review = params["review_days"] > 0 and me["urgency"] != "normal" and t - me["last_ask"] >= params["review_days"]
        if (me["news"] or review) and me["asked"] < params["max_asks"]:
            ask.append(i)
    state["ask"] = ask
    # ---- public events ----
    if t == rd:
        events.append({"kind": "alert", "text": {
            "en": "A post spreads on social media: toilet paper will run out.", "ja": "SNS で投稿が広がる：「トイレットペーパーがなくなる」。"},
            "fact": {"subject": "rumour", "predicate": "status", "object": "spreading"}})
    if t == tv and params["tv_coverage"] > 0:
        events.append({"kind": "alert", "text": {
            "en": "TV shows empty shelves and queues all day.", "ja": "テレビが空の棚と行列を一日中流す。"}})
    if t == st + 1:
        events.append({"kind": "info", "text": {
            "en": "Makers and the government: almost all toilet paper is made at home, stock is plentiful, please do not hoard.",
            "ja": "業界団体と政府：「ほとんどが国内生産で、在庫は十分。買いだめは控えてほしい」。"},
            "fact": {"subject": "makers", "predicate": "statement", "object": "stock is plentiful"}})
    if t == params["limit_day"]:
        events.append({"kind": "info", "text": {
            "en": "Shops limit sales to %d pack per customer." % params["limit_packs"], "ja": "店が「お 1 人様 %d 点まで」にする。" % params["limit_packs"]}})
    if t == params["extra_supply_day"]:
        events.append({"kind": "milestone", "text": {
            "en": "Extra shipments from the makers start reaching the shops.", "ja": "メーカーの増産分が店に届き始める。"}})
    return events


def default_rule(h, me, peers):
    """What the household does with no AI: a fixed formula of worry, what it saw, and what others do."""
    score = (0.9 * (1 if me["aware"] else 0) * h["anxiety"] + 1.2 * (1 if me["saw_empty"] else 0) * (0.4 + 0.6 * h["anxiety"])
             + 2.0 * peers * h["conformity"] - 0.8 * (1 if me["statement"] else 0) * h["trust"] - 1.0 * (1 if me["saw_refill"] else 0))
    score = max(0.0, score)
    choice = "today" if score > 0.75 else ("soon" if score > 0.4 else "normal")
    return {"choice": choice, "numbers": {
        "reorder": round(normal_reorder(h) + 12 * min(2.0, score * 1.5)), "packs": 2 if score > 0.9 else 1,
        "tries": 1 + min(3, int(round(score * 2)))}}


def situation(params, h, me, state, t):
    blind = params["blind"]
    day_use = h["members"] * params["rolls_per_person_day"]
    lines = []
    if blind:
        lines.append("It is the morning of day %d (%s), late winter. An unfamiliar infectious disease has been in the news for weeks; masks have been hard to find." % (t, DAYS[t % 7]))
    else:
        lines.append("It is the morning of %s 2020 in Japan. The new coronavirus has been in the news for weeks; masks have been sold out everywhere, and schools have just been asked to close." % date_text(t))
    lines.append("At home you have %d rolls of toilet paper, about %d days for your household of %d. You normally buy a 12-roll pack when you are down to about %d rolls." % (
        round(me["stock"]), round(me["stock"] / day_use) if day_use > 0 else 99, h["members"], normal_reorder(h)))
    heard = []
    if me["aware"]:
        if blind:
            heard.append("You have heard, %s, that toilet paper is about to run out because its raw material comes from the country where the disease started." % (
                {"sns": "in posts spreading on social media", "tv": "on TV", "chat": "from family and friends", "low": "from people around you"}[h["info"]]))
        else:
            heard.append("You have heard, %s, that toilet paper will run out because it is made in China and imports are stopping." % (
                {"sns": "in posts spreading on Twitter", "tv": "on TV, which keeps showing empty shelves and queues", "chat": "from family and friends on LINE", "low": "from people around you"}[h["info"]]))
    if me["statement"]:
        heard.append("You have also heard the makers' association and the government say that almost all toilet paper is made in the country, stock is plentiful, and people should not hoard.")
    if me["saw_empty"]:
        heard.append("At your usual shop you saw the toilet paper shelf completely empty.")
    if me["failed"] >= 2:
        heard.append("You have gone out to buy it %d times and come back with nothing." % me["failed"])
    if me["saw_refill"]:
        heard.append("On your last trip the shelf was full again.")
    if t >= params["limit_day"]:
        heard.append("Shops allow %d pack per customer." % params["limit_packs"])
    peers = sum(state["extra_buyers"][-2:]) / len(state["homes"]) if state["extra_buyers"] else 0.0
    if peers > 0.02:
        heard.append("You get the impression that roughly %d in 100 households around you bought extra in the last two days." % round(peers * 100))
    if not heard:
        heard.append("Nothing unusual has reached you about toilet paper.")
    return " ".join(lines + heard)


def decisions(state, params, t):
    people = params["_data"]["households"]
    peers = sum(state["extra_buyers"][-2:]) / len(people) if state["extra_buyers"] else 0.0
    reqs = []
    for i in state["ask"]:
        h, me = people[i], state["homes"][i]
        me["asked"] += 1
        me["last_ask"] = t
        me["news"] = []
        cur = me["reorder"]
        reqs.append({
            "key": "home:%d" % h["id"], "agent": "household", "node": "store%d" % (h["id"] % STORES), "mode": "pick",
            "name": h["name"],
            "persona": "%s, %s; %s; lives in a %s; %s. %s" % (h["kind"], h["age"], h["work"], h["area"], h["info_text"], h["story"]),
            "situation": situation(params, h, me, state, t),
            "facts": {"rolls_at_home": round(me["stock"]), "people_at_home": h["members"], "rolls_used_per_week": round(h["members"] * params["rolls_per_person_day"] * 7, 1),
                      "usual_days_between_shopping_trips": h["shop_gap"]},
            "question": "What do you do about toilet paper from today? Choose how urgently you act, and set your own numbers.",
            "options": [
                {"id": "normal", "label": {"en": "Nothing special: buy on a usual shopping trip when I run low", "ja": "特別なことはしない：いつもの買い物で、減ったら買う"}},
                {"id": "soon", "label": {"en": "Look for it on my next trips, even though I am not out yet", "ja": "まだあるが、次の買い物から探す"}},
                {"id": "today", "label": {"en": "Go out today just to get some", "ja": "今日、これだけのために買いに行く"}},
            ],
            "numbers": [
                {"id": "reorder", "label": {"en": "Rolls at home below which I want to buy", "ja": "家の在庫が何ロールを切ったら買いたいか"}, "min": 0, "max": 72, "default": cur},
                {"id": "packs", "label": {"en": "12-roll packs I try to buy per trip", "ja": "1 回に買おうとするパック数（12 ロール入り）"}, "min": 1, "max": 4, "default": me["packs"]},
                {"id": "tries", "label": {"en": "Shops I am willing to visit in one day if the first is empty", "ja": "売り切れのとき 1 日に回る店の数"}, "min": 1, "max": 4, "default": me["tries"]},
            ],
            "default": default_rule(h, me, peers),
        })
    return reqs


def apply(state, params, rng, t, action):
    i = int(action["key"].split(":")[1])
    me = state["homes"][i]
    n = action.get("numbers") or {}
    me["urgency"] = action.get("choice") or "normal"
    me["reorder"] = max(0.0, float(n.get("reorder", me["reorder"])))
    me["packs"] = max(1, int(round(n.get("packs", me["packs"]))))
    me["tries"] = max(1, int(round(n.get("tries", me["tries"]))))
    return None


def index(state, values):
    return sum(values) / (len(values) * state["daily_packs"]) * 100 if values else 100.0


def metrics(state, params, t):
    people = params["_data"]["households"]
    sales = state["sales"]
    homes = state["homes"]
    supply = sorted(me["stock"] / (h["members"] * params["rolls_per_person_day"]) for h, me in zip(people, homes))
    week = sales[7:14] if len(sales) >= 14 else []
    return {
        "sales_index": round(index(state, sales[-1:]), 1) if sales else 100.0,
        "last7_index": round(index(state, sales[-7:]), 1) if sales else 100.0,
        "demand_index": round(index(state, state["wanted"][-1:]), 1) if state["wanted"] else 100.0,
        "feb28_demand": round(index(state, state["wanted"][11:12]), 1) if len(state["wanted"]) > 11 else 0.0,
        "week_feb24_demand": round(index(state, state["wanted"][7:14]), 1) if len(state["wanted"]) >= 14 else 0.0,
        "peak_index": round(max(index(state, [s]) for s in sales), 1) if sales else 100.0,
        "feb28_index": round(index(state, sales[11:12]), 1) if len(sales) > 11 else 0.0,
        "week_feb24_index": round(index(state, week), 1) if week else 0.0,
        "empty_shops": round(sum(1 for s in range(STORES) if shelf(state, s) == "empty") / STORES * 100, 1),
        "failed_trips": state["failed"][-1] if state["failed"] else 0,
        "aware": round(sum(1 for me in homes if me["aware"]) / len(homes) * 100, 1),
        "calmed": round(sum(1 for me in homes if me["aware"] and me["urgency"] == "normal") / max(1, sum(1 for me in homes if me["aware"])) * 100, 1),
        "median_days_supply": round(supply[len(supply) // 2], 1),
        "stocked_up": round(sum(1 for d in supply if d > 60) / len(supply) * 100, 1),
        "shop_stock": round(sum(state["stores"]) / (state["target"] * STORES) * 100, 1),
    }


def view(state, params, t):
    nodes, links = [], []
    people = params["_data"]["households"]
    whole_max = state["daily_packs"] * params["wholesale_days"]
    nodes.append({"id": "makers", "label": {"en": "Makers and wholesaler", "ja": "メーカー・卸"}, "x": 8, "y": 46, "value": state["wholesale"], "max": max(1.0, whole_max),
                  "sub": {"en": "sent %d packs this morning / buffer %d" % (round(state["delivered"]), round(state["wholesale"])),
                          "ja": "今朝の出荷 %d パック / 卸の在庫 %d" % (round(state["delivered"]), round(state["wholesale"]))},
                  "status": "crit" if state["wholesale"] < state["daily_packs"] else "ok"})
    for s in range(STORES):
        st = shelf(state, s)
        n = sum(1 for h in people if h["id"] % STORES == s)
        nodes.append({"id": "store%d" % s, "label": {"en": "Shop %d" % (s + 1), "ja": "店 %d" % (s + 1)}, "x": 34 + (s % 2) * 16, "y": 14 + (s // 2) * 32 + (s % 2) * 8,
                      "value": state["stores"][s], "max": state["target"], "status": "crit" if st == "empty" else ("warn" if st == "low" else "ok"),
                      "sub": {"en": "%d packs / %d homes" % (round(state["stores"][s]), n), "ja": "在庫 %d パック / %d 世帯" % (round(state["stores"][s]), n)}})
        links.append({"a": "makers", "b": "store%d" % s, "value": state["delivered"] / STORES, "max": state["daily_packs"] * 2.5 / STORES})
        links.append({"a": "store%d" % s, "b": "homes", "value": (state["sales"][-1] if state["sales"] else 0) / STORES, "max": state["daily_packs"] * 1.2})
    m = metrics(state, params, t)
    nodes.append({"id": "homes", "label": {"en": "240 households", "ja": "240 世帯"}, "x": 84, "y": 46, "value": m["median_days_supply"], "max": 90,
                  "sub": {"en": "median %d days of paper / %d%% heard the rumour" % (round(m["median_days_supply"]), round(m["aware"])),
                          "ja": "在庫の中央値 %d 日分 / うわさを聞いた %d%%" % (round(m["median_days_supply"]), round(m["aware"]))}, "status": "ok"})
    return {"clock": {"en": date_text(t) + " (morning)", "ja": date_ja(t) + " 朝"}, "nodes": nodes, "links": links}


def on_params(state, params, patch, t):
    return None


def invariants(state, params, t):
    bad = []
    if any(s < -1e-6 for s in state["stores"]):
        bad.append("a shop has negative stock")
    if any(me["stock"] < -1e-6 for me in state["homes"]):
        bad.append("a household has negative stock")
    return bad
