"""Izu Oshima: a small island economy tied to its ferries.

Math: seasonal visitor demand with frequency / fare / room-price elasticities, seat and
bed capacity limits, sector accounts (lodging, services, fishing & farming), a labour
market, the ferry operator's profit and loss, and population change.
AI residents set the behaviour terms: schedule and fares, prices, hiring, where the
catch is sold, who leaves, who moves in, and whether visitors come at all.
Tick = 1 week.
"""
import math
import random

BASE_JET_FARE = 9980.0
BASE_SHIP_FARE = 6160.0
BASE_ROOM_PRICE = 12000.0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# visitor segments: share of base demand, share who prefer the jet, nights, spend per head (yen, excluding lodging)
SEG = {
    "day_tripper": {"share": 0.30, "jet": 0.90, "nights": 0.0, "spend": 6000},
    "weekender": {"share": 0.40, "jet": 0.70, "nights": 1.3, "spend": 16000},
    "active": {"share": 0.20, "jet": 0.50, "nights": 2.0, "spend": 20000},
    "group": {"share": 0.10, "jet": 0.40, "nights": 1.0, "spend": 12000},
}
BASE_VISIT = 0.5          # share of interested people who actually come, with no special reason either way
QUARTER = 13


def week_of_year(params, t):
    return (int(params["start_week"]) - 1 + t - 1) % 52 + 1


def season(w):
    """Relative demand by week of year (mean close to 1)."""
    s = 0.62
    s += 0.55 * math.exp(-0.5 * ((w - 8) / 3.5) ** 2)     # camellia festival, late Jan - Mar
    s += 0.95 * math.exp(-0.5 * ((w - 18) / 1.2) ** 2)    # Golden Week
    s += 1.35 * math.exp(-0.5 * ((w - 32) / 3.5) ** 2)    # summer holidays
    s += 0.35 * math.exp(-0.5 * ((w - 47) / 2.0) ** 2)    # autumn weekends
    return s / 0.975


def clock(params, t):
    """English clock text, used in the questions put to residents."""
    if t <= 0:
        return "Start"
    w = week_of_year(params, t)
    year = (int(params["start_week"]) - 1 + t - 1) // 52 + 1
    return "Year %d, week %d (%s)" % (year, w, MONTHS[min(11, (w - 1) * 12 // 52)])


def clock_text(params, t):
    if t <= 0:
        return {"en": "Start", "ja": "開始"}
    w = week_of_year(params, t)
    year = (int(params["start_week"]) - 1 + t - 1) // 52 + 1
    return {"en": clock(params, t), "ja": "%d 年目 第 %d 週（%d 月）" % (year, w, min(11, (w - 1) * 12 // 52) + 1)}


def init(params, rng):
    pop = float(params["population"])
    return {
        "young": pop * 0.12, "working": pop * 0.35, "old": pop * 0.38, "kids": pop * 0.15,
        "jet_sailings": float(params["jet_sailings"]), "jet_fare": float(params["jet_fare"]),
        "beds": float(params["beds"]), "room_price": BASE_ROOM_PRICE,
        "staff": {"lodging": 250.0, "services": 800.0, "primary": 250.0},
        "cash": {"lodging": 150e6, "services": 400e6, "primary": 80e6, "town": float(params["town_budget"])},
        "policy": {
            "inn": {"expand": 0.1, "hold": 0.8, "shrink": 0.1}, "inn_price": 0.0,
            "shop": {"hire": 0.2, "hold": 0.7, "cut": 0.1}, "local_sourcing": 0.3,
            "fish": {"local": 0.5, "tokyo": 0.4, "reduce": 0.1},
            "young": {"stay": 0.7, "leave": 0.3}, "migrant": {"move": 0.2, "not": 0.8},
            "visit": {k: BASE_VISIT for k in SEG},
            "town": "save",
        },
        "promo_weeks": 0, "housing_weeks": 0, "subsidy_weeks": 0,
        "ferry_cum": 0.0, "moved_in": 0.0, "moved_out": 0.0,
        "ask_now": True,
        "last": {"visitors": 0.0, "unserved": 0.0, "turned_away": 0.0, "jet_pax": 0.0, "ship_pax": 0.0,
                 "jet_load": 0.0, "ship_load": 0.0, "ferry_profit": 0.0, "tourism_rev": 0.0, "bed_nights": 0.0,
                 "occupancy": 0.0, "income": 0.0, "cancel_jet": 0.0, "primary_rev": 0.0, "services_rev": 0.0,
                 "lodging_profit": 0.0, "services_profit": 0.0, "vacancies": 0.0, "unemployed": 0.0},
        "hist_rev": [],
    }


def population(state):
    return state["young"] + state["working"] + state["old"] + state["kids"]


def weather(params, t):
    """Share of sailings cancelled this week. Same in every branch of a run."""
    exo = random.Random(params["_seed"] * 100003 + t)
    w = week_of_year(params, t)
    sev = params["weather_severity"]
    jet = 0.04
    if w >= 49 or w <= 9:
        jet += 0.07                      # winter westerlies
    if 31 <= w <= 42 and exo.random() < 0.22 * sev:
        jet += exo.uniform(0.2, 0.55)    # typhoon week
    jet = min(0.9, jet * sev * exo.uniform(0.7, 1.3))
    return jet, jet * 0.4


def step(state, params, rng, t):
    events = []
    pol = state["policy"]
    w = week_of_year(params, t)
    if params["schedule_control"] == "fixed":
        state["jet_sailings"] = float(params["jet_sailings"])
        state["jet_fare"] = float(params["jet_fare"])
    state["beds"] = max(100.0, state["beds"])
    pop = population(state)
    cancel_jet, cancel_ship = weather(params, t)
    if cancel_jet > 0.3:
        events.append({"kind": "alert", "node": "jet", "text": {
            "en": "Rough seas: about %d%% of jet ferry sailings are cancelled this week." % round(cancel_jet * 100),
            "ja": "海が荒れ、今週はジェット船の約 %d%% が欠航。" % round(cancel_jet * 100)}})

    # ---- ferry seats (one direction per week) ----
    jet_sail = max(0.0, state["jet_sailings"])
    ship_sail = max(0.0, float(params["ship_sailings"]))
    seats_jet = jet_sail * 7 * params["jet_seats"] * (1 - cancel_jet)
    seats_ship = ship_sail * 7 * params["ship_seats"] * (1 - cancel_ship)
    subsidy = 0.10 if state["subsidy_weeks"] > 0 else 0.0
    jet_fare_paid = state["jet_fare"] * (1 - subsidy)
    ship_fare_paid = float(params["ship_fare"]) * (1 - subsidy)

    res_trips = pop * 0.04
    res_jet = min(seats_jet * 0.5, res_trips * 0.6)
    res_ship = min(seats_ship * 0.5, res_trips - res_jet)

    # ---- visitor demand ----
    freq = ((jet_sail + 0.4 * ship_sail) / (2.0 + 0.4)) ** params["frequency_elasticity"] if (jet_sail + ship_sail) > 0 else 0.0
    f_jet = (jet_fare_paid / BASE_JET_FARE) ** params["price_elasticity"]
    f_ship = (ship_fare_paid / BASE_SHIP_FARE) ** params["price_elasticity"]
    f_room = (state["room_price"] / BASE_ROOM_PRICE) ** (-0.4)
    need_staff = max(1.0, state["last"]["services_rev"] / 260000.0) if state["last"]["services_rev"] > 0 else state["staff"]["services"]
    service_ok = min(1.0, state["staff"]["services"] / need_staff)
    crowd_pen = 0.08 if state["last"]["occupancy"] > 0.92 else 0.0
    attract = 0.75 + 0.25 * service_ok - crowd_pen
    promo = params["promo_boost"] * (1.08 if state["promo_weeks"] > 0 else 1.0)
    base = params["annual_visitors"] / 52.0 * season(w) * promo * attract * freq
    exo = random.Random(params["_seed"] * 100003 + t + 77)
    base *= exo.uniform(0.92, 1.08)

    want = {}
    for k, s in SEG.items():
        d = base * s["share"] * (pol["visit"][k] / BASE_VISIT)
        if k == "day_tripper" and jet_sail < 2:
            d *= 0.25                    # a day trip needs an early boat out and a late boat back
        if s["nights"] > 0:
            d *= f_room
        want[k] = {"jet": d * s["jet"] * f_jet, "ship": d * (1 - s["jet"]) * f_ship}

    # beds limit overnight visitors
    bn_want = sum((v["jet"] + v["ship"]) * SEG[k]["nights"] for k, v in want.items())
    bed_cap = state["beds"] * 7 * 0.95
    bed_ratio = min(1.0, bed_cap / bn_want) if bn_want > 0 else 1.0
    turned_away = 0.0
    for k, v in want.items():
        if SEG[k]["nights"] > 0:
            turned_away += (v["jet"] + v["ship"]) * (1 - bed_ratio)
            v["jet"] *= bed_ratio
            v["ship"] *= bed_ratio

    # seats limit everyone; part of the overflow moves to the other boat
    jet_want = sum(v["jet"] for v in want.values())
    ship_want = sum(v["ship"] for v in want.values())
    jet_room = max(0.0, seats_jet * 0.95 - res_jet)
    ship_room = max(0.0, seats_ship * 0.95 - res_ship)
    jet_ok = min(1.0, jet_room / jet_want) if jet_want > 0 else 1.0
    ship_ok = min(1.0, ship_room / ship_want) if ship_want > 0 else 1.0
    spill_to_ship = min(max(0.0, ship_room - ship_want * ship_ok), jet_want * (1 - jet_ok) * 0.4)
    spill_to_jet = min(max(0.0, jet_room - jet_want * jet_ok), ship_want * (1 - ship_ok) * 0.4)
    jet_pax = jet_want * jet_ok + spill_to_jet
    ship_pax = ship_want * ship_ok + spill_to_ship
    visitors = jet_pax + ship_pax
    wanted_total = jet_want + ship_want
    unserved = max(0.0, wanted_total - visitors)
    served_ratio = visitors / wanted_total if wanted_total > 0 else 0.0

    bed_nights = 0.0
    spend = 0.0
    for k, v in want.items():
        n = (v["jet"] + v["ship"]) * served_ratio
        bed_nights += n * SEG[k]["nights"]
        spend += n * SEG[k]["spend"]

    # ---- ferry operator: profit and loss for this route ----
    yield_ = 0.8
    revenue = (jet_pax * 2 * jet_fare_paid * yield_ + ship_pax * 2 * ship_fare_paid * yield_
               + res_jet * 2 * state["jet_fare"] * 0.65 + res_ship * 2 * params["ship_fare"] * 0.65)
    subsidy_cost = (jet_pax * 2 * state["jet_fare"] + ship_pax * 2 * params["ship_fare"]) * subsidy * yield_
    revenue += subsidy_cost
    state["cash"]["town"] -= subsidy_cost
    cost = (jet_sail * 7 * (1 - cancel_jet) * params["jet_cost_per_trip"]
            + ship_sail * 7 * (1 - cancel_ship) * params["ship_cost_per_trip"] + params["ferry_fixed_cost"])
    ferry_profit = revenue - cost
    state["ferry_cum"] += ferry_profit

    # ---- island businesses ----
    st, cash = state["staff"], state["cash"]
    lodging_rev = bed_nights * state["room_price"]
    resident_spend = state["last"]["income"] * 0.55 if state["last"]["income"] > 0 else pop * 45000.0 * 0.55
    services_rev = spend + resident_spend
    ls = pol["local_sourcing"]
    local_food_demand = services_rev * 0.25 * ls
    potential = st["primary"] * 75000.0
    f = pol["fish"]
    sold_local = min(local_food_demand, potential * f["local"])
    sold_tokyo = potential * f["tokyo"] * 1.1 * (1 - cancel_ship) * (1.0 if ship_sail > 0 else 0.0)
    primary_rev = sold_local + sold_tokyo
    lodging_profit = lodging_rev * (1 - 0.35) - st["lodging"] * 70000.0 - state["beds"] * 4000.0
    services_profit = services_rev * (1 - 0.58 - 0.02 * ls) - st["services"] * 62000.0 - 25e6
    primary_profit = primary_rev * 0.55 - st["primary"] * 30000.0
    cash["lodging"] += lodging_profit
    cash["services"] += services_profit
    cash["primary"] += primary_profit

    # hiring follows demand, at a speed the owners choose; limited by people looking for work
    labour = (state["young"] + state["working"]) * 0.8
    fixed_jobs = 800.0 + 300.0
    targets = {"lodging": bed_nights / 30.0 + state["beds"] * 0.06, "services": services_rev / 260000.0,
               "primary": 250.0 * (1 - 0.6 * f["reduce"])}
    speed = {"lodging": pol["shop"], "services": pol["shop"], "primary": {"hire": 0.3, "hold": 0.6, "cut": 0.3}}
    vacancies = 0.0
    for k in ("lodging", "services", "primary"):
        gap = targets[k] - st[k]
        rate = 0.02 + 0.15 * (speed[k]["hire"] if gap > 0 else speed[k]["cut"])
        if cash[k] < 0 and gap > 0:
            rate = 0.0                   # no money, no hiring
        employed_now = sum(st.values()) + fixed_jobs
        change = gap * rate
        if change > 0:
            free = max(0.0, labour - employed_now)
            vacancies += max(0.0, change - free)
            change = min(change, free)
        st[k] = max(5.0, st[k] + change)
    employed = sum(st.values()) + fixed_jobs
    unemployed = max(0.0, labour - employed)

    # weekly room price and bed stock move a little, in the direction the innkeepers chose
    state["room_price"] = max(5000.0, min(30000.0, state["room_price"] * (1 + pol["inn_price"] / 100.0 / QUARTER)))
    inn = pol["inn"]
    if cash["lodging"] > 0:
        add = state["beds"] * 0.012 * inn["expand"] / QUARTER * 4
        state["beds"] += add
        cash["lodging"] -= add * 3.0e6          # building a bed costs about 3 million yen (assumed)
    state["beds"] -= state["beds"] * 0.02 * inn["shrink"] / QUARTER * 4
    if cash["lodging"] < -50e6:
        state["beds"] *= 0.995                   # inns close when the losses pile up

    wages = st["lodging"] * 70000.0 + st["services"] * 62000.0 + st["primary"] * 30000.0 + 800.0 * 90000.0 + 300.0 * 65000.0
    owner_income = max(0.0, lodging_profit + services_profit + primary_profit) * 0.3
    income = wages + state["old"] * 35000.0 + owner_income

    # ---- people ----
    nat = params["natural_change_year"] / 52.0
    state["old"] += state["old"] * nat * 2.2
    state["kids"] += state["kids"] * nat * 0.3
    leave = state["young"] * (0.01 + 0.07 * pol["young"]["leave"]) / QUARTER
    state["young"] -= leave
    state["moved_out"] += leave
    jobs_pull = min(2.0, 0.6 + vacancies / 20.0 + (0.3 if unemployed < labour * 0.04 else 0.0))
    access = min(1.6, (jet_sail / 2.0) ** 0.5) if jet_sail > 0 else 0.4
    housing = 1.5 if state["housing_weeks"] > 0 else 1.0
    arrive = 7.5 / QUARTER * (pol["migrant"]["move"] / 0.2) * jobs_pull * access * housing * params["migrant_appeal"]
    state["young"] += arrive * 0.5
    state["working"] += arrive * 0.3
    state["kids"] += arrive * 0.2
    state["moved_in"] += arrive
    aging = state["young"] / (17.0 * 52.0)
    state["young"] -= aging
    state["working"] += aging
    grow_up = state["kids"] / (18.0 * 52.0)
    state["kids"] -= grow_up
    state["young"] += grow_up * 0.45             # more than half leave for school or work on the mainland
    retire = state["working"] / (29.0 * 52.0)
    state["working"] -= retire
    state["old"] += retire

    for k in ("promo_weeks", "housing_weeks", "subsidy_weeks"):
        if state[k] > 0:
            state[k] -= 1

    tourism_rev = lodging_rev + spend
    state["hist_rev"] = (state["hist_rev"] + [tourism_rev])[-4:]
    state["last"] = {
        "visitors": visitors, "unserved": unserved, "turned_away": turned_away, "jet_pax": jet_pax, "ship_pax": ship_pax,
        "jet_load": (jet_pax + res_jet) / seats_jet if seats_jet > 0 else 0.0,
        "ship_load": (ship_pax + res_ship) / seats_ship if seats_ship > 0 else 0.0,
        "ferry_profit": ferry_profit, "tourism_rev": tourism_rev, "bed_nights": bed_nights,
        "occupancy": bed_nights / (state["beds"] * 7) if state["beds"] > 0 else 0.0, "income": income,
        "cancel_jet": cancel_jet, "primary_rev": primary_rev, "services_rev": services_rev,
        "lodging_profit": lodging_profit, "services_profit": services_profit,
        "vacancies": vacancies, "unemployed": unemployed,
    }
    if t > 1 and (t - 1) % 52 == 0:
        events.append({"kind": "milestone", "node": "town", "text": {
            "en": "One year has passed. Population %d; the ferry route has made %s yen so far." % (round(population(state)), fmt_yen(state["ferry_cum"])),
            "ja": "1 年が過ぎた。人口 %d 人。フェリー航路の累計損益は %d 百万円。" % (round(population(state)), round(state["ferry_cum"] / 1e6))}})
    return events


def fmt_yen(v):
    """Yen in millions, e.g. 12M."""
    return "%.0fM" % (v / 1e6)


def seen(state, params, t):
    """Numbers any resident could know from the last few weeks."""
    L = state["last"]
    return {
        "week": clock(params, t), "season_index_now": round(season(week_of_year(params, t)), 2),
        "season_index_next_quarter": round(sum(season((week_of_year(params, t) + i - 1) % 52 + 1) for i in range(1, 14)) / 13, 2),
        "jet_sailings_per_day": round(state["jet_sailings"], 1), "jet_fare_yen": round(state["jet_fare"]),
        "ship_sailings_per_day": params["ship_sailings"], "ship_fare_yen": params["ship_fare"],
        "visitors_last_week": round(L["visitors"]), "visitors_who_could_not_get_a_seat": round(L["unserved"]),
        "jet_load_pct": round(L["jet_load"] * 100), "ship_load_pct": round(L["ship_load"] * 100),
        "room_price_yen": round(state["room_price"]), "beds": round(state["beds"]),
        "bed_occupancy_pct": round(L["occupancy"] * 100), "population": round(population(state)),
        "unemployed": round(L["unemployed"]), "unfilled_jobs": round(L["vacancies"]),
    }


def decisions(state, params, t):
    if not (state["ask_now"] or (t - 1) % QUARTER == 0):
        return []
    state["ask_now"] = False
    S = seen(state, params, t)
    L = state["last"]
    cash = state["cash"]
    reqs = []
    lead = "It is %s on Izu Oshima (population %d). " % (S["week"], S["population"])

    if params["schedule_control"] == "operator":
        reqs.append({
            "key": "ferry_operator", "agent": "ferry_operator", "node": "jet", "mode": "pick",
            "situation": lead + "Jet ferry: %s round trips a day at %d yen one way, load %d%% last week; about %d people could not get a seat. "
            "Large ship: %s a day at %d yen, load %d%%. This route made %s yen last week and %s yen in total so far. One extra daily jet round trip costs about %s yen a week."
            % (S["jet_sailings_per_day"], S["jet_fare_yen"], S["jet_load_pct"], S["visitors_who_could_not_get_a_seat"],
               S["ship_sailings_per_day"], S["ship_fare_yen"], S["ship_load_pct"], fmt_yen(L["ferry_profit"]), fmt_yen(state["ferry_cum"]),
               fmt_yen(7 * params["jet_cost_per_trip"])),
            "facts": S, "question": "Set the jet ferry timetable and fare for the next three months.",
            "options": [],
            "numbers": [
                {"id": "jet_sailings", "label": {"en": "Jet round trips per day", "ja": "ジェット船の 1 日の往復数"}, "min": 1, "max": 6, "default": round(state["jet_sailings"])},
                {"id": "jet_fare", "label": {"en": "Jet one-way fare (yen)", "ja": "ジェット船の片道運賃（円）"}, "min": 6000, "max": 14000, "default": round(state["jet_fare"])},
            ],
            "default": {"numbers": {"jet_sailings": round(state["jet_sailings"]), "jet_fare": round(state["jet_fare"])}},
        })
    reqs.append({
        "key": "innkeepers", "agent": "innkeepers", "node": "inns", "mode": "split",
        "population": int(round(state["beds"] / 25)),
        "situation": lead + "Inns and hotels have %d beds at an average %d yen a night; %d%% were filled last week. Lodging made %s yen last week; the sector holds %s yen in cash. "
        "Jet ferries run %s times a day." % (S["beds"], S["room_price_yen"], S["bed_occupancy_pct"], fmt_yen(L["lodging_profit"]), fmt_yen(cash["lodging"]), S["jet_sailings_per_day"]),
        "facts": S, "question": "Over the next three months, how do the island's innkeepers split between expanding, holding and shrinking? And how do room prices move?",
        "options": [
            {"id": "expand", "label": {"en": "Invest: add beds, renovate", "ja": "投資する：ベッドを増やす、改装する"}},
            {"id": "hold", "label": {"en": "Keep things as they are", "ja": "現状を保つ"}},
            {"id": "shrink", "label": {"en": "Shrink or close", "ja": "縮小する、廃業する"}},
        ],
        "numbers": [{"id": "price_change_pct", "label": {"en": "Room price change over the quarter (%)", "ja": "この四半期の宿泊料の変化（%）"}, "min": -15, "max": 15, "default": 0}],
        "default": {"weights": {"expand": 0.1 + (0.2 if L["occupancy"] > 0.6 else 0.0), "hold": 0.75, "shrink": 0.05 + (0.2 if cash["lodging"] < 0 else 0.0)},
                    "numbers": {"price_change_pct": 3 if L["occupancy"] > 0.6 else (-3 if L["occupancy"] < 0.2 else 0)}},
    })
    reqs.append({
        "key": "shop_owners", "agent": "shop_owners", "node": "shops", "mode": "split",
        "population": 180,
        "situation": lead + "Restaurants, shops and activity operators earned %s yen last week (tourists and residents together) and made %s yen. They employ %d people; %d islanders are looking for work and %d jobs went unfilled."
        % (fmt_yen(L["services_rev"]), fmt_yen(L["services_profit"]), round(state["staff"]["services"]), S["unemployed"], S["unfilled_jobs"]),
        "facts": S, "question": "How do owners split on staffing for the next three months, and what share of their food do they buy from island fishers and farmers?",
        "options": [
            {"id": "hire", "label": {"en": "Hire for the coming season", "ja": "次の季節に向けて雇う"}},
            {"id": "hold", "label": {"en": "Keep the same staff", "ja": "今の人数を保つ"}},
            {"id": "cut", "label": {"en": "Cut hours and staff", "ja": "勤務時間と人を減らす"}},
        ],
        "numbers": [{"id": "local_sourcing", "label": {"en": "Share of food bought on the island (0-1)", "ja": "島内で仕入れる食材の割合（0〜1）"}, "min": 0.05, "max": 0.7, "default": round(state["policy"]["local_sourcing"], 2)}],
        "default": {"weights": {"hire": 0.2 + (0.2 if S["season_index_next_quarter"] > 1.1 else 0.0), "hold": 0.6, "cut": 0.1 + (0.2 if S["season_index_next_quarter"] < 0.8 else 0.0)},
                    "numbers": {"local_sourcing": round(state["policy"]["local_sourcing"], 2)}},
    })
    reqs.append({
        "key": "fishers", "agent": "fishers", "node": "harbor", "mode": "split", "population": int(round(state["staff"]["primary"])),
        "situation": lead + "Island fishers and farmers earned %s yen last week. Local restaurants buy about %d%% of their food on the island. Selling in Tokyo pays about 10%% more but depends on the large ship (%s sailing a day; cargo is lost when it is cancelled)."
        % (fmt_yen(L["primary_rev"]), round(state["policy"]["local_sourcing"] * 100), S["ship_sailings_per_day"]),
        "facts": S, "question": "How do fishers and farmers split their effort over the next three months?",
        "options": [
            {"id": "local", "label": {"en": "Sell to island restaurants and shops", "ja": "島内の飲食店や店に売る"}},
            {"id": "tokyo", "label": {"en": "Ship to Tokyo markets", "ja": "東京の市場に出荷する"}},
            {"id": "reduce", "label": {"en": "Work less or quit", "ja": "仕事を減らす、やめる"}},
        ],
        "default": {"weights": {"local": 0.5, "tokyo": 0.4, "reduce": 0.1}},
    })
    reqs.append({
        "key": "young_islanders", "agent": "young_islanders", "node": "town", "mode": "split", "population": int(round(state["young"])),
        "situation": lead + "About %d islanders are aged 18-35. %d people are looking for work and %d jobs are unfilled. Tokyo is %s jet trips a day away (%d yen one way)."
        % (round(state["young"]), S["unemployed"], S["unfilled_jobs"], S["jet_sailings_per_day"], S["jet_fare_yen"]),
        "facts": S, "question": "Over the next three months, what share of young islanders are leaning towards staying, and what share towards leaving for the mainland?",
        "options": [
            {"id": "stay", "label": {"en": "Stay on the island", "ja": "島に残る"}},
            {"id": "leave", "label": {"en": "Leave for the mainland", "ja": "本土へ出る"}},
        ],
        "default": {"weights": {"stay": 0.7, "leave": 0.3}},
    })
    reqs.append({
        "key": "would_be_migrants", "agent": "would_be_migrants", "node": "tokyo", "mode": "split", "population": 400,
        "situation": lead + "People on the mainland who have thought about moving to the island see: %d unfilled jobs, %s jet trips a day to Tokyo at %d yen, housing support from the town: %s."
        % (S["unfilled_jobs"], S["jet_sailings_per_day"], S["jet_fare_yen"], "yes" if state["housing_weeks"] > 0 else "no"),
        "facts": S, "question": "What share of them actually take steps to move in the next three months?",
        "options": [
            {"id": "move", "label": {"en": "Take steps to move to the island", "ja": "島への移住に動く"}},
            {"id": "not", "label": {"en": "Not now", "ja": "今は動かない"}},
        ],
        "default": {"weights": {"move": 0.2, "not": 0.8}},
    })
    for k in SEG:
        reqs.append({
            "key": "visitors:" + k, "agent": k, "node": "tokyo", "mode": "split",
            "population": int(round(params["annual_visitors"] / 4 * SEG[k]["share"] / BASE_VISIT)),
            "situation": "It is %s. People in the Tokyo area who are considering a trip to Izu Oshima see: jet ferry %s times a day, %d yen one way, 1h45m; large overnight ship %d yen; rooms about %d yen a night; last week %d%% of jet seats were taken and about %d people could not get a seat."
            % (S["week"], S["jet_sailings_per_day"], round(state["jet_fare"] * (0.9 if state["subsidy_weeks"] > 0 else 1.0)), round(params["ship_fare"]), S["room_price_yen"], S["jet_load_pct"], S["visitors_who_could_not_get_a_seat"]),
            "facts": {"season_index_next_quarter": S["season_index_next_quarter"], "jet_sailings_per_day": S["jet_sailings_per_day"],
                      "jet_fare_yen": S["jet_fare_yen"], "room_price_yen": S["room_price_yen"], "jet_load_pct": S["jet_load_pct"]},
            "question": "Of the people in this group who are considering Izu Oshima for the next three months, what share actually go?",
            "options": [
                {"id": "visit", "label": {"en": "Go to Izu Oshima", "ja": "伊豆大島に行く"}},
                {"id": "elsewhere", "label": {"en": "Go somewhere else (Atami, Hakone, ...)", "ja": "別の場所に行く（熱海、箱根など）"}},
                {"id": "stay_home", "label": {"en": "Do not travel", "ja": "旅行しない"}},
            ],
            "default": {"weights": {"visit": BASE_VISIT, "elsewhere": 0.3, "stay_home": 0.2}},
        })
    reqs.append({
        "key": "town_office", "agent": "town_office", "node": "townhall", "mode": "pick",
        "situation": lead + "The town has %s yen left for discretionary measures. Visitors last week: %d. People who moved in so far: %d; moved out: %d."
        % (fmt_yen(cash["town"]), S["visitors_last_week"], round(state["moved_in"]), round(state["moved_out"])),
        "facts": S, "question": "Which one measure does the town fund for the next three months?",
        "options": [
            {"id": "promo", "label": {"en": "Tourism campaign in Tokyo (15M yen)", "ja": "東京での観光キャンペーン（1,500 万円）"}},
            {"id": "housing", "label": {"en": "Housing support for people moving in (10M yen)", "ja": "移住者への住宅支援（1,000 万円）"}},
            {"id": "ferry_subsidy", "label": {"en": "Pay 10% of every ferry fare", "ja": "船の運賃の 10% を町が負担"}},
            {"id": "save", "label": {"en": "Spend nothing this quarter", "ja": "今期は何もしない"}},
        ],
        "default": {"choice": "save"},
    })
    return reqs


def norm(weights, keys):
    w = {k: max(0.0, float(weights.get(k, 0.0))) for k in keys}
    tot = sum(w.values()) or 1.0
    return {k: v / tot for k, v in w.items()}


def apply(state, params, rng, t, action):
    pol, key = state["policy"], action["key"]
    nums = action.get("numbers") or {}
    if key == "ferry_operator":
        old = state["jet_sailings"]
        state["jet_sailings"] = float(round(nums.get("jet_sailings", old)))
        state["jet_fare"] = float(round(nums.get("jet_fare", state["jet_fare"]) / 10) * 10)
        if state["jet_sailings"] != old:
            return [{"kind": "info", "node": "jet", "text": {
                "en": "The ferry operator changes the jet timetable: %d round trips a day (was %d), fare %d yen." % (state["jet_sailings"], old, state["jet_fare"]),
                "ja": "船会社がジェット船のダイヤを変更：1 日 %d 往復（前は %d）、運賃 %d 円。" % (state["jet_sailings"], old, state["jet_fare"])},
                "fact": {"subject": "jet_ferry", "predicate": "round_trips_per_day", "object": state["jet_sailings"]}}]
    elif key == "innkeepers":
        pol["inn"] = norm(action["weights"], ["expand", "hold", "shrink"])
        pol["inn_price"] = float(nums.get("price_change_pct", 0.0))
    elif key == "shop_owners":
        pol["shop"] = norm(action["weights"], ["hire", "hold", "cut"])
        pol["local_sourcing"] = float(nums.get("local_sourcing", pol["local_sourcing"]))
    elif key == "fishers":
        pol["fish"] = norm(action["weights"], ["local", "tokyo", "reduce"])
    elif key == "young_islanders":
        pol["young"] = norm(action["weights"], ["stay", "leave"])
    elif key == "would_be_migrants":
        pol["migrant"] = norm(action["weights"], ["move", "not"])
    elif key.startswith("visitors:"):
        w = norm(action["weights"], ["visit", "elsewhere", "stay_home"])
        pol["visit"][key.split(":")[1]] = w["visit"]
    elif key == "town_office":
        choice = action.get("choice")
        cost = {"promo": 15e6, "housing": 10e6}.get(choice, 0.0)
        if choice in ("promo", "housing") and state["cash"]["town"] < cost:
            choice = "save"
        pol["town"] = choice
        if choice == "promo":
            state["promo_weeks"] = QUARTER
            state["cash"]["town"] -= cost
        elif choice == "housing":
            state["housing_weeks"] = QUARTER
            state["cash"]["town"] -= cost
        elif choice == "ferry_subsidy" and state["cash"]["town"] > 0:
            state["subsidy_weeks"] = QUARTER
        if choice != "save":
            label = {"promo": ("a tourism campaign", "観光キャンペーン"), "housing": ("housing support for newcomers", "移住者への住宅支援"),
                     "ferry_subsidy": ("a 10% ferry fare subsidy", "船の運賃の 10% 補助")}[choice]
            return [{"kind": "info", "node": "townhall", "text": {
                "en": "The town office funds %s for the next three months." % label[0],
                "ja": "町役場が、次の 3 か月の%sを決めた。" % label[1]},
                "fact": {"subject": "town_office", "predicate": "measure", "object": choice}}]
    return None


def on_params(state, params, patch, t):
    state["ask_now"] = True       # everyone reconsiders after an outside change
    events = []
    if "extra_beds" in patch:
        state["beds"] += float(patch["extra_beds"])
        params["extra_beds"] = 0
        events.append({"kind": "info", "node": "inns", "text": {
            "en": "A new hotel opens: %d more beds." % patch["extra_beds"], "ja": "新しいホテルが開業：ベッドが %d 増えた。" % patch["extra_beds"]}})
    if "jet_sailings" in patch or "jet_fare" in patch:
        state["jet_sailings"] = float(params["jet_sailings"])
        state["jet_fare"] = float(params["jet_fare"])
    return events


def metrics(state, params, t):
    L = state["last"]
    pop = population(state)
    hist = state["hist_rev"]
    return {
        "population": round(pop), "young": round(state["young"]),
        "visitors": round(L["visitors"]), "unserved": round(L["unserved"] + L["turned_away"]),
        "jet_load": round(L["jet_load"] * 100, 1), "jet_sailings": round(state["jet_sailings"], 1),
        "ferry_profit": round(L["ferry_profit"]), "ferry_profit_cum": round(state["ferry_cum"]),
        "tourism_revenue": round(sum(hist) / len(hist)) if hist else 0,
        "occupancy": round(L["occupancy"] * 100, 1), "room_price": round(state["room_price"]), "beds": round(state["beds"]),
        "employed": round(sum(state["staff"].values()) + 1100), "unemployed": round(L["unemployed"]),
        "income_per_capita": round(L["income"] * 52 / pop) if pop > 0 else 0,
        "business_cash": round(state["cash"]["lodging"] + state["cash"]["services"] + state["cash"]["primary"]),
    }


def view(state, params, t):
    L = state["last"]
    pop = population(state)

    def node(i, en, ja, x, y, value, mx, sub_en, sub_ja, status="ok"):
        return {"id": i, "label": {"en": en, "ja": ja}, "x": x, "y": y, "value": value, "max": mx, "status": status,
                "sub": {"en": sub_en, "ja": sub_ja}}

    jl = L["jet_load"]
    nodes = [
        node("tokyo", "Tokyo (Takeshiba)", "東京（竹芝）", 8, 40, L["visitors"], params["annual_visitors"] / 52 * 2.5,
             "%d visitors this week" % round(L["visitors"]), "今週の来島者 %d 人" % round(L["visitors"])),
        node("jet", "Jet ferry", "ジェット船", 30, 22, L["jet_pax"], max(1.0, state["jet_sailings"] * 7 * params["jet_seats"]),
             "%d a day, load %d%%" % (round(state["jet_sailings"]), round(jl * 100)), "1 日 %d 往復、乗船率 %d%%" % (round(state["jet_sailings"]), round(jl * 100)),
             "crit" if L["cancel_jet"] > 0.3 else ("warn" if jl > 0.9 else "ok")),
        node("ship", "Large ship", "大型客船", 30, 60, L["ship_pax"], max(1.0, params["ship_sailings"] * 7 * params["ship_seats"]),
             "load %d%%" % round(L["ship_load"] * 100), "乗船率 %d%%" % round(L["ship_load"] * 100)),
        node("port", "Port (Okada / Motomachi)", "港（岡田・元町）", 50, 40, L["visitors"], params["annual_visitors"] / 52 * 2.5,
             "%d could not come" % round(L["unserved"] + L["turned_away"]), "来られなかった人 %d" % round(L["unserved"] + L["turned_away"]),
             "warn" if L["unserved"] + L["turned_away"] > L["visitors"] * 0.15 else "ok"),
        node("inns", "Inns and hotels", "宿", 68, 18, L["occupancy"], 1.0,
             "%d beds, %d%% full, %d yen" % (round(state["beds"]), round(L["occupancy"] * 100), round(state["room_price"])),
             "ベッド %d、稼働 %d%%、%d 円" % (round(state["beds"]), round(L["occupancy"] * 100), round(state["room_price"])),
             "warn" if L["occupancy"] > 0.9 or state["cash"]["lodging"] < 0 else "ok"),
        node("shops", "Restaurants and shops", "飲食店・商店", 72, 46, state["staff"]["services"], 1200,
             "%d staff" % round(state["staff"]["services"]), "働く人 %d" % round(state["staff"]["services"]),
             "warn" if state["cash"]["services"] < 0 else "ok"),
        node("harbor", "Fishing and farms", "漁業・農業", 60, 78, state["staff"]["primary"], 400,
             "%d workers" % round(state["staff"]["primary"]), "働く人 %d" % round(state["staff"]["primary"])),
        node("town", "Residents", "島の住民", 88, 66, pop, params["population"] * 1.2,
             "%d people, %d young" % (round(pop), round(state["young"])), "%d 人（若者 %d）" % (round(pop), round(state["young"])),
             "warn" if pop < params["population"] * 0.95 else "ok"),
        node("townhall", "Town office", "町役場", 90, 30, max(0.0, state["cash"]["town"]), max(1.0, params["town_budget"]),
             "budget left %sM" % round(state["cash"]["town"] / 1e6), "残り予算 %s 百万円" % round(state["cash"]["town"] / 1e6)),
    ]
    links = [
        {"a": "tokyo", "b": "jet", "value": L["jet_pax"], "max": max(1.0, 6 * 7 * params["jet_seats"])},
        {"a": "jet", "b": "port", "value": L["jet_pax"], "max": max(1.0, 6 * 7 * params["jet_seats"])},
        {"a": "tokyo", "b": "ship", "value": L["ship_pax"], "max": max(1.0, 6 * 7 * params["jet_seats"])},
        {"a": "ship", "b": "port", "value": L["ship_pax"], "max": max(1.0, 6 * 7 * params["jet_seats"])},
        {"a": "port", "b": "inns", "value": L["bed_nights"], "max": max(1.0, state["beds"] * 7)},
        {"a": "port", "b": "shops", "value": L["visitors"], "max": params["annual_visitors"] / 52 * 2.5},
        {"a": "town", "b": "shops", "value": state["staff"]["services"], "max": 1200},
        {"a": "harbor", "b": "shops", "value": state["policy"]["local_sourcing"], "max": 0.7},
        {"a": "harbor", "b": "ship", "value": state["policy"]["fish"]["tokyo"], "max": 1.0},
        {"a": "townhall", "b": "town", "value": 1, "max": 4},
    ]
    return {"clock": clock_text(params, t), "nodes": nodes, "links": links}


def invariants(state, params, t):
    bad = []
    L = state["last"]
    for k in ("young", "working", "old", "kids", "beds"):
        if state[k] < 0:
            bad.append("%s is negative" % k)
    if L["jet_load"] > 1.0001 or L["ship_load"] > 1.0001:
        bad.append("more passengers than seats")
    if L["occupancy"] > 1.0001:
        bad.append("more guests than beds")
    for k, v in state["staff"].items():
        if v < 0:
            bad.append("negative staff in %s" % k)
    return bad
