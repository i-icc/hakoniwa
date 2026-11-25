"""Chuo Line stoppage on a weekday morning.

Math: commuter arrivals (bell curve), platform crowds, detour and taxi queues with
fixed capacities, a recovery ramp after service resumes, and a logit choice model
that gives each cohort's default split. AI residents replace that default split.
Tick = 5 minutes, starting at 07:00.
"""
import math
import random

TICK_MIN = 5
START_MIN = 7 * 60

# zone: share of commuters, normal minutes to Shinjuku, detour (extra minutes, people per tick),
# taxi (fare to Shinjuku in yen, taxis per tick). All figures are assumptions.
ZONES = [
    {"id": "tachikawa", "en": "Tachikawa", "ja": "立川", "share": 0.17, "normal": 27, "extra": 25, "cap": 900,
     "fare": 11000, "taxis": 14, "detour_en": "Nambu Line to Bubaigawara, then Keio Line",
     "detour_ja": "南武線で分倍河原へ、京王線に乗り換え"},
    {"id": "kokubunji", "en": "Kokubunji", "ja": "国分寺", "share": 0.15, "normal": 21, "extra": 30, "cap": 600,
     "fare": 8800, "taxis": 10, "detour_en": "Seibu Kokubunji Line, then Seibu Shinjuku Line",
     "detour_ja": "西武国分寺線から西武新宿線"},
    {"id": "koganei", "en": "Musashi-Koganei", "ja": "武蔵小金井", "share": 0.14, "normal": 23, "extra": 40, "cap": 250,
     "fare": 7600, "taxis": 8, "detour_en": "bus to the Keio Line (Fuchu / Chofu)",
     "detour_ja": "バスで京王線（府中・調布）へ"},
    {"id": "mitaka", "en": "Mitaka", "ja": "三鷹", "share": 0.14, "normal": 18, "extra": 15, "cap": 1500,
     "fare": 5800, "taxis": 12, "detour_en": "Chuo-Sobu local / Tozai through trains (running, packed)",
     "detour_ja": "中央・総武線各駅停車、東西線直通（運転中だが大混雑）"},
    {"id": "kichijoji", "en": "Kichijoji", "ja": "吉祥寺", "share": 0.16, "normal": 15, "extra": 15, "cap": 1800,
     "fare": 4900, "taxis": 14, "detour_en": "Keio Inokashira Line",
     "detour_ja": "京王井の頭線"},
    {"id": "ogikubo", "en": "Ogikubo", "ja": "荻窪", "share": 0.13, "normal": 10, "extra": 12, "cap": 1600,
     "fare": 3600, "taxis": 12, "detour_en": "Marunouchi Line",
     "detour_ja": "丸ノ内線"},
    {"id": "nakano", "en": "Nakano", "ja": "中野", "share": 0.11, "normal": 5, "extra": 8, "cap": 2000,
     "fare": 2300, "taxis": 12, "detour_en": "Tozai Line / Sobu local",
     "detour_ja": "東西線、総武線各駅停車"},
]
ZONE = {z["id"]: z for z in ZONES}

# archetype: share, value of time (yen per minute), cost of giving up (in minutes-equivalent)
ARCH = {
    "strict": {"share": 0.35, "vot": 80, "giveup": "strict_giveup_cost"},
    "flex": {"share": 0.35, "vot": 60, "giveup": 45},
    "student": {"share": 0.15, "vot": 15, "giveup": 120},
    "errand": {"share": 0.15, "vot": 40, "giveup": 60},
}
MODES = ["wait", "detour", "taxi", "give_up"]

PEOPLE = [
    {"id": "kenji", "agent": "kenji", "zone": "kokubunji", "arrive_tick_after": 1, "en": "Kenji", "ja": "ケンジ"},
    {"id": "mika", "agent": "mika", "zone": "kichijoji", "arrive_tick_after": 2, "en": "Mika", "ja": "ミカ"},
    {"id": "sato", "agent": "sato", "zone": "tachikawa", "arrive_tick_after": 0, "en": "Sato", "ja": "サトウ"},
]


def clock(t):
    m = START_MIN + t * TICK_MIN
    return "%02d:%02d" % (m // 60, m % 60)


def profile(t):
    m = (t - 0.5) * TICK_MIN
    return math.exp(-0.5 * ((m - 50.0) / 35.0) ** 2)


PROFILE_SUM = sum(profile(i) for i in range(1, 37))
PEAK = profile(10)


def incident_tick(params):
    return int(round(params["incident_minute"] / TICK_MIN)) + 1


def resume_tick(params):
    return incident_tick(params) + int(math.ceil(params["suspension_minutes"] / TICK_MIN))


def init(params, rng):
    cohorts = {}
    for z in ZONES:
        for a in ARCH:
            cohorts[z["id"] + ":" + a] = {
                "policy": {"wait": 1.0, "detour": 0.0, "taxi": 0.0, "give_up": 0.0},
                "waiting": 0.0, "wait_sum": 0.0, "detour_q": 0.0, "taxi_q": 0.0,
            }
    people = []
    for p in PEOPLE:
        people.append({"id": p["id"], "status": "not_yet", "mode": None, "eta": None, "delay": None, "since": None})
    return {
        "service": "normal", "factor": 1.0,
        "est_known": False, "est_resume_tick": None,
        "cohorts": cohorts, "people": people,
        "entered": 0.0, "arrived": 0.0, "delay_sum": 0.0, "gave_up": 0.0, "late": 0.0,
        "taxi_spend": 0.0, "chosen": {"wait": 0.0, "detour": 0.0, "taxi": 0.0, "give_up": 0.0},
        "ask": [], "ask_reason": "", "last_seen": {},
    }


def zone_queues(state, zid):
    d = sum(state["cohorts"][zid + ":" + a]["detour_q"] for a in ARCH)
    x = sum(state["cohorts"][zid + ":" + a]["taxi_q"] for a in ARCH)
    w = sum(state["cohorts"][zid + ":" + a]["waiting"] for a in ARCH)
    return w, d, x


def detour_cap(params, z):
    return max(1.0, z["cap"] * params["detour_capacity_factor"])


def taxi_cap(params, z):
    return max(0.5, z["taxis"] * params["taxi_supply_factor"] * 1.6)


def outlook(state, params, zid, t):
    """What a person at this station can observe (all in minutes / yen)."""
    z = ZONE[zid]
    w, d, x = zone_queues(state, zid)
    detour_wait = d / detour_cap(params, z) * TICK_MIN
    taxi_wait = x / taxi_cap(params, z) * TICK_MIN
    crowd = min(20.0, detour_wait * 0.5)
    if state["service"] == "suspended":
        if state["est_known"] and state["est_resume_tick"] is not None:
            remaining = max(5.0, (state["est_resume_tick"] - t) * TICK_MIN)
        else:
            remaining = None
    else:
        remaining = 0.0
    return {
        "platform_crowd": int(round(w)), "detour_queue_min": round(detour_wait, 1),
        "detour_total_min": round(detour_wait + z["extra"] + crowd, 1),
        "taxi_queue_min": round(taxi_wait, 1),
        "taxi_total_min": round(taxi_wait + z["normal"] * 0.8, 1),
        "taxi_fare_yen": int(round(z["fare"] * params["taxi_fare_factor"])),
        "est_remaining_min": remaining,
    }


def default_weights(state, params, zid, arch, t):
    """Logit choice over generalised cost (minutes). This is the no-AI behaviour."""
    o = outlook(state, params, zid, t)
    a = ARCH[arch]
    if state["service"] != "suspended":
        board_wait = o["platform_crowd"] / max(1.0, board_cap(params, ZONE[zid], state["factor"])) * TICK_MIN
        c_wait = board_wait
    else:
        c_wait = (o["est_remaining_min"] if o["est_remaining_min"] is not None else 45.0 + 15.0) + 5.0
    giveup = params["strict_giveup_cost"] if a["giveup"] == "strict_giveup_cost" else a["giveup"]
    cost = {
        "wait": c_wait,
        "detour": o["detour_total_min"],
        "taxi": o["taxi_total_min"] + o["taxi_fare_yen"] / 1.6 / a["vot"],
        "give_up": float(giveup),
    }
    temp = 14.0
    best = min(cost.values())
    ex = {k: math.exp(-(v - best) / temp) for k, v in cost.items()}
    s = sum(ex.values())
    return {k: round(v / s, 3) for k, v in ex.items()}


def board_cap(params, z, factor):
    peak_flow = params["commuters_total"] * z["share"] * PEAK / PROFILE_SUM
    return peak_flow * 1.25 * factor


def finish(state, n, delay_min, t, arch):
    if n <= 0:
        return
    state["arrived"] += n
    state["delay_sum"] += n * delay_min
    if arch in ("strict", "student") and delay_min > 20:
        state["late"] += n


def step(state, params, rng, t):
    events = []
    it, rt = incident_tick(params), resume_tick(params)
    ask_all = False
    reason = ""

    # ---- service state ----
    if t == it and state["service"] == "normal":
        state["service"] = "suspended"
        state["factor"] = 0.0
        ask_all, reason = True, "suspended"
        events.append({"kind": "alert", "node": "koganei",
                       "text": {"en": "Chuo Line rapid service is suspended: a person was hit by a train near Musashi-Koganei. No estimate yet.",
                                "ja": "中央線快速は運転見合わせ。武蔵小金井駅付近で人身事故。再開見込みは未定。"},
                       "fact": {"subject": "chuo_line", "predicate": "service", "object": "suspended"}})
    if state["service"] == "suspended":
        first = it + int(round(params["announce_delay"] / TICK_MIN))
        second = it + int(round(params["suspension_minutes"] * 0.5 / TICK_MIN))
        if t == first and t < rt:
            est_min = params["suspension_minutes"] * params["estimate_bias"]
            state["est_known"] = True
            state["est_resume_tick"] = it + int(math.ceil(est_min / TICK_MIN))
            ask_all, reason = True, "estimate"
            events.append({"kind": "info", "text": {
                "en": "Operator: service is expected to resume around %s." % clock(state["est_resume_tick"]),
                "ja": "運転再開は %s ごろの見込み、と発表。" % clock(state["est_resume_tick"])},
                "fact": {"subject": "chuo_line", "predicate": "resume_estimate", "object": clock(state["est_resume_tick"])}})
        elif t == second and t > first and t < rt and state["est_resume_tick"] != rt:
            state["est_known"] = True
            state["est_resume_tick"] = rt
            ask_all, reason = True, "estimate_changed"
            events.append({"kind": "alert", "text": {
                "en": "Operator revises the estimate: service will resume around %s." % clock(rt),
                "ja": "再開見込みを %s ごろに変更、と発表。" % clock(rt)},
                "fact": {"subject": "chuo_line", "predicate": "resume_estimate", "object": clock(rt)}})
        if t >= rt:
            state["service"] = "recovering"
            state["factor"] = params["recovery_capacity"]
            ask_all, reason = True, "resumed"
            events.append({"kind": "milestone", "text": {
                "en": "Chuo Line rapid service resumes, with fewer trains and heavy delays.",
                "ja": "中央線快速が運転再開。本数を減らし、大幅な遅れ。"},
                "fact": {"subject": "chuo_line", "predicate": "service", "object": "recovering"}})
    elif state["service"] == "recovering" and t > rt:
        state["factor"] = min(1.0, state["factor"] + 0.1)
        if state["factor"] >= 1.0:
            state["service"] = "normal"
            events.append({"kind": "milestone", "text": {"en": "Service is back to the normal timetable.",
                                                         "ja": "平常ダイヤに戻った。"},
                           "fact": {"subject": "chuo_line", "predicate": "service", "object": "normal"}})

    # ---- people arrive and move ----
    exo = random.Random(params["_seed"] * 100003 + t)
    base = params["commuters_total"] * profile(t) / PROFILE_SUM
    r = params["reconsider_rate"]
    disrupted = state["service"] != "normal"
    for z in ZONES:
        noise = 1.0 + exo.uniform(-0.05, 0.05)
        zid = z["id"]
        # pass 1: new arrivals and people who change their mind are split by each cohort's policy
        arrivals = {}
        for a, spec in ARCH.items():
            c = state["cohorts"][zid + ":" + a]
            n = base * z["share"] * spec["share"] * noise
            arrivals[a] = n
            state["entered"] += n
            pol = c["policy"] if disrupted else {"wait": 1.0, "detour": 0.0, "taxi": 0.0, "give_up": 0.0}
            mv_w = r * c["waiting"] if disrupted else 0.0
            mv_d = 0.5 * r * c["detour_q"]
            mv_x = 0.5 * r * c["taxi_q"]
            if c["waiting"] > 0:
                c["wait_sum"] -= c["wait_sum"] * (mv_w / c["waiting"])
            c["waiting"] -= mv_w
            c["detour_q"] -= mv_d
            c["taxi_q"] -= mv_x
            pool = n + mv_w + mv_d + mv_x
            c["waiting"] += pool * pol["wait"]
            c["detour_q"] += pool * pol["detour"]
            c["taxi_q"] += pool * pol["taxi"]
            state["gave_up"] += pool * pol["give_up"]
            if disrupted:
                for m in MODES:
                    state["chosen"][m] += n * pol[m]
        # pass 2: detours, taxis and trains serve the queues, shared in proportion to who is queueing
        w_tot, d_tot, x_tot = zone_queues(state, zid)
        dcap, tcap, bcap = detour_cap(params, z), taxi_cap(params, z), board_cap(params, z, state["factor"])
        d_wait = d_tot / dcap * TICK_MIN
        x_wait = x_tot / tcap * TICK_MIN
        crowd = min(20.0, d_wait * 0.5)
        d_ratio = min(1.0, dcap / d_tot) if d_tot > 0 else 0.0
        x_ratio = min(1.0, tcap / x_tot) if x_tot > 0 else 0.0
        b_ratio = (min(1.0, bcap / w_tot) if w_tot > 0 else 0.0) if state["factor"] > 0 else 0.0
        slow = 10.0 * (1.0 - state["factor"])
        for a in ARCH:
            c = state["cohorts"][zid + ":" + a]
            served = c["detour_q"] * d_ratio
            c["detour_q"] -= served
            finish(state, served, d_wait + z["extra"] + crowd, t, a)
            served = c["taxi_q"] * x_ratio
            c["taxi_q"] -= served
            finish(state, served, x_wait + z["normal"] * 0.8, t, a)
            state["taxi_spend"] += served * z["fare"] * params["taxi_fare_factor"] / 1.6
            if b_ratio > 0 and c["waiting"] > 0:
                boarded = c["waiting"] * b_ratio
                avg_wait = c["wait_sum"] / c["waiting"]
                finish(state, boarded, avg_wait + slow, t, a)
                c["wait_sum"] -= avg_wait * boarded
                c["waiting"] -= boarded
            c["wait_sum"] += c["waiting"] * TICK_MIN
            for k in ("waiting", "detour_q", "taxi_q", "wait_sum"):
                if c[k] < 1e-6:
                    c[k] = 0.0

    # ---- named individuals ----
    for meta, p in zip(PEOPLE, state["people"]):
        z = ZONE[meta["zone"]]
        if p["status"] == "not_yet" and t >= it + meta["arrive_tick_after"]:
            p["status"] = "waiting"
            p["since"] = t
        elif p["status"] == "waiting" and state["factor"] > 0:
            w_tot, _, _ = zone_queues(state, z["id"])
            if w_tot <= board_cap(params, z, state["factor"]) * 2:
                p["status"] = "arrived"
                p["delay"] = (t - p["since"]) * TICK_MIN + 10.0 * (1.0 - state["factor"])
                p["mode"] = p["mode"] or "wait"
        elif p["status"] in ("detour", "taxi") and p["eta"] is not None and t >= p["eta"]:
            p["status"] = "arrived"
        if p["status"] == "arrived" and not p.get("announced"):
            p["announced"] = True
            events.append({"kind": "milestone", "node": "shinjuku", "agent": meta["agent"], "text": {
                "en": "%s reaches central Tokyo at %s, about %d minutes late (%s)." % (meta["en"], clock(t), round(p["delay"] or 0), p["mode"]),
                "ja": "%sが %s に都心へ到着。約 %d 分の遅れ（%s）。" % (meta["ja"], clock(t), round(p["delay"] or 0), p["mode"])}})

    # ---- who should be asked this tick ----
    ask = []
    if ask_all:
        ask = [z["id"] for z in ZONES]
    elif state["service"] == "suspended":
        for z in ZONES:
            o = outlook(state, params, z["id"], t)
            seen = state["last_seen"].get(z["id"])
            if seen is None:
                continue
            moved = max(abs(o["detour_total_min"] - seen["detour"]), abs(o["taxi_total_min"] - seen["taxi"]))
            if moved >= params["reask_minutes"] and t - seen["t"] >= 3:
                ask.append(z["id"])
                reason = "queues_changed"
    state["ask"] = ask
    state["ask_reason"] = reason
    return events


def situation_text(state, params, zid, t):
    z = ZONE[zid]
    o = outlook(state, params, zid, t)
    it = incident_tick(params)
    if state["service"] == "suspended":
        if o["est_remaining_min"] is None:
            head = "Chuo Line rapid service has been suspended since %s (person hit by a train). No estimate of when it resumes." % clock(it - 1)
        else:
            head = "Chuo Line rapid service has been suspended since %s. The operator says it should resume around %s (about %d min from now); earlier estimates may have been wrong." % (
                clock(it - 1), clock(state["est_resume_tick"]), o["est_remaining_min"])
    else:
        head = "Chuo Line rapid service has just resumed with fewer trains; platforms are packed and trains run about %d min slow." % round(10 * (1 - state["factor"]))
    return ("%s You are at %s station at %s; normally it is %d min to Shinjuku. About %d people are waiting on the platform. "
            "Detour (%s): about %d min in total longer than usual, including a %d min queue. "
            "Taxi: about %d min queue, about %d yen to Shinjuku (can be shared)." % (
                head, z["en"], clock(t), z["normal"], o["platform_crowd"], z["detour_en"],
                o["detour_total_min"], o["detour_queue_min"], o["taxi_queue_min"], o["taxi_fare_yen"]))


def options_for(zid):
    z = ZONE[zid]
    return [
        {"id": "wait", "label": {"en": "Wait at the station for the Chuo Line", "ja": "駅で中央線の再開を待つ"}},
        {"id": "detour", "label": {"en": "Detour: " + z["detour_en"], "ja": "迂回：" + z["detour_ja"]}},
        {"id": "taxi", "label": {"en": "Take a taxi", "ja": "タクシーに乗る"}},
        {"id": "give_up", "label": {"en": "Give up: go home, work remotely or skip today", "ja": "あきらめる：帰宅・在宅勤務・今日は休む"}},
    ]


def decisions(state, params, t):
    reqs = []
    for zid in state["ask"]:
        o = outlook(state, params, zid, t)
        state["last_seen"][zid] = {"detour": o["detour_total_min"], "taxi": o["taxi_total_min"], "t": t}
        text = situation_text(state, params, zid, t)
        for a in ARCH:
            c = state["cohorts"][zid + ":" + a]
            pop = c["waiting"] + c["detour_q"] + c["taxi_q"]
            reqs.append({
                "key": "commuters:%s:%s" % (zid, a), "agent": a, "node": zid, "mode": "split",
                "population": int(round(pop + params["commuters_total"] * ZONE[zid]["share"] * ARCH[a]["share"] * profile(t + 1) / PROFILE_SUM * 3)),
                "situation": text, "facts": o,
                "question": "How do the people of this group at this station split between the options over the next 15 minutes?",
                "options": options_for(zid),
                "default": {"weights": default_weights(state, params, zid, a, t)},
            })
    if state["ask"] or state["ask_reason"]:
        for meta, p in zip(PEOPLE, state["people"]):
            if p["status"] != "waiting":
                continue
            zid = meta["zone"]
            if zid not in state["ask"] and p["since"] != t:
                continue
            w = default_weights(state, params, zid, "strict" if meta["id"] != "sato" else "flex", t)
            reqs.append({
                "key": "person:" + meta["id"], "agent": meta["agent"], "node": zid, "mode": "pick",
                "situation": situation_text(state, params, zid, t) + " You have been here for %d minutes." % ((t - p["since"]) * TICK_MIN),
                "facts": outlook(state, params, zid, t),
                "question": "What do you do now?",
                "options": options_for(zid),
                "default": {"choice": max(w, key=lambda k: w[k])},
            })
    else:
        for meta, p in zip(PEOPLE, state["people"]):
            if p["status"] == "waiting" and p["since"] == t:
                zid = meta["zone"]
                w = default_weights(state, params, zid, "strict" if meta["id"] != "sato" else "flex", t)
                reqs.append({
                    "key": "person:" + meta["id"], "agent": meta["agent"], "node": zid, "mode": "pick",
                    "situation": situation_text(state, params, zid, t) + " You have just arrived at the station.",
                    "facts": outlook(state, params, zid, t), "question": "What do you do now?",
                    "options": options_for(zid), "default": {"choice": max(w, key=lambda k: w[k])},
                })
    return reqs


def apply(state, params, rng, t, action):
    key = action["key"]
    if key.startswith("commuters:"):
        _, zid, a = key.split(":")
        w = {m: max(0.0, float(action["weights"].get(m, 0.0))) for m in MODES}
        tot = sum(w.values()) or 1.0
        state["cohorts"][zid + ":" + a]["policy"] = {m: v / tot for m, v in w.items()}   # shares must sum to exactly 1
        return None
    if key.startswith("person:"):
        pid = key.split(":")[1]
        for meta, p in zip(PEOPLE, state["people"]):
            if meta["id"] != pid or p["status"] != "waiting":
                continue
            z = ZONE[meta["zone"]]
            o = outlook(state, params, z["id"], t)
            waited = (t - p["since"]) * TICK_MIN
            choice = action.get("choice")
            if choice == "detour":
                p["status"], p["mode"] = "detour", "detour"
                p["delay"] = waited + o["detour_total_min"]
                p["eta"] = t + int(math.ceil((o["detour_total_min"] + z["normal"]) / TICK_MIN))
            elif choice == "taxi":
                p["status"], p["mode"] = "taxi", "taxi"
                p["delay"] = waited + o["taxi_total_min"]
                p["eta"] = t + int(math.ceil((o["taxi_total_min"] + z["normal"]) / TICK_MIN))
            elif choice == "give_up":
                p["status"], p["mode"] = "home", "give_up"
                return [{"kind": "info", "agent": meta["agent"], "node": z["id"], "text": {
                    "en": "%s gives up at %s and heads home." % (meta["en"], clock(t)),
                    "ja": "%sは %s にあきらめて帰宅。" % (meta["ja"], clock(t))}}]
            else:
                p["mode"] = "wait"
    return None


def on_params(state, params, patch, t):
    if "suspension_minutes" in patch and state["service"] == "suspended":
        return [{"kind": "alert", "text": {
            "en": "The stoppage is now expected to last until about %s (not yet announced to passengers)." % clock(resume_tick(params)),
            "ja": "運転見合わせは %s ごろまで続く見込みに変わった（乗客にはまだ未発表）。" % clock(resume_tick(params))}}]
    return None


def metrics(state, params, t):
    w = d = x = 0.0
    for c in state["cohorts"].values():
        w += c["waiting"]
        d += c["detour_q"]
        x += c["taxi_q"]
    ch = state["chosen"]
    tot = sum(ch.values()) or 1.0
    return {
        "stranded": round(w + d + x), "platform_crowd": round(w), "detour_queue": round(d), "taxi_queue": round(x),
        "arrived": round(state["arrived"]), "gave_up": round(state["gave_up"]), "late_arrivals": round(state["late"]),
        "avg_delay": round(state["delay_sum"] / state["arrived"], 2) if state["arrived"] > 0 else 0.0,
        "share_wait": round(ch["wait"] / tot * 100, 1), "share_detour": round(ch["detour"] / tot * 100, 1),
        "share_taxi": round(ch["taxi"] / tot * 100, 1), "share_give_up": round(ch["give_up"] / tot * 100, 1),
        "taxi_spend": round(state["taxi_spend"]), "service_level": round(state["factor"] * 100),
    }


def view(state, params, t):
    nodes, links = [], []
    n = len(ZONES)
    biggest = params["commuters_total"] * 0.03
    for i, z in enumerate(ZONES):
        w, d, x = zone_queues(state, z["id"])
        total = w + d + x
        status = "ok" if total < biggest * 0.25 else ("warn" if total < biggest * 0.7 else "crit")
        nodes.append({"id": z["id"], "label": {"en": z["en"], "ja": z["ja"]}, "x": 6 + i * 12, "y": 30 if i % 2 == 0 else 52,
                      "value": round(total), "max": round(biggest), "status": status,
                      "sub": {"en": "platform %d / detour %d / taxi %d" % (round(w), round(d), round(x)),
                              "ja": "ホーム %d / 迂回 %d / タクシー %d" % (round(w), round(d), round(x))}})
    nodes.append({"id": "shinjuku", "label": {"en": "Shinjuku / central Tokyo", "ja": "新宿・都心"}, "x": 94, "y": 30,
                  "value": round(state["arrived"]), "max": round(params["commuters_total"]), "status": "ok",
                  "sub": {"en": "arrived %d" % round(state["arrived"]), "ja": "到着 %d" % round(state["arrived"])}})
    nodes.append({"id": "home", "label": {"en": "Gave up", "ja": "あきらめた"}, "x": 50, "y": 90,
                  "value": round(state["gave_up"]), "max": round(params["commuters_total"] * 0.3), "status": "ok",
                  "sub": {"en": "%d people" % round(state["gave_up"]), "ja": "%d 人" % round(state["gave_up"])}})
    for i in range(n - 1):
        links.append({"a": ZONES[i]["id"], "b": ZONES[i + 1]["id"], "value": state["factor"], "max": 1.0})
    links.append({"a": ZONES[-1]["id"], "b": "shinjuku", "value": state["factor"], "max": 1.0})
    return {"clock": clock(t), "nodes": nodes, "links": links}


def invariants(state, params, t):
    inside = 0.0
    for c in state["cohorts"].values():
        inside += c["waiting"] + c["detour_q"] + c["taxi_q"]
        for k in ("waiting", "detour_q", "taxi_q"):
            if c[k] < -1e-6:
                return ["negative %s" % k]
    total = inside + state["arrived"] + state["gave_up"]
    if abs(total - state["entered"]) > max(1.0, state["entered"] * 1e-6):
        return ["people are not conserved: entered %.1f, accounted %.1f" % (state["entered"], total)]
    return []
