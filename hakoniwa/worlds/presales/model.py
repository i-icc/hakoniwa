"""Presales department for server hardware: which team structure works best?

Math: deals arrive at random (same arrivals in every branch), each deal is a chain of
stages with work hours; people have skills, daily capacity, fatigue and a limit on
parallel work; team structure decides who may work on what and where handoffs happen;
win probability depends on quality and timeliness.
AI residents set behaviour: how the manager prioritises, how engineers cope with load,
how sales reps react to waiting, how patient customers are, what the head invests in.
Tick = 1 working day.
"""
import math
import random

DOMAINS = ["server", "gpu", "storage", "network"]
SEGMENTS = {
    # share, base win rate, median deal size (million yen), days allowed
    "enterprise": {"share": 0.30, "win": 0.35, "size": 40, "days": 15},
    "public": {"share": 0.15, "win": 0.30, "size": 30, "days": 10},      # tenders: late = lost
    "smb": {"share": 0.35, "win": 0.45, "size": 6, "days": 7},
    "ai_startup": {"share": 0.20, "win": 0.40, "size": 25, "days": 8},
}
LEVELS = {"senior": {"speed": 1.25, "top": 3}, "mid": {"speed": 1.0, "top": 2}, "junior": {"speed": 0.85, "top": 1}}
SKILL_SPEED = [0.6, 0.85, 1.0, 1.15]
SKILL_QUALITY = [0.5, 0.75, 0.92, 1.0]
OVERHEAD = {"pool": 0.12, "product_squads": 0.10, "account_pods": 0.15, "triage": 0.10}
ORG_SQUADS = {
    "pool": ["pool"],
    "product_squads": ["server", "gpu", "infra"],
    "account_pods": ["enterprise", "public", "growth"],
    "triage": ["desk", "specialists"],
}
SQUAD_LABEL = {
    "pool": ("One shared pool", "共有プール"), "server": ("Server squad", "サーバー班"), "gpu": ("GPU / AI squad", "GPU・AI 班"),
    "infra": ("Storage and network squad", "ストレージ・ネットワーク班"), "enterprise": ("Enterprise pod", "大企業担当"),
    "public": ("Public sector pod", "官公庁担当"), "growth": ("SMB and startup pod", "中小・スタートアップ担当"),
    "desk": ("Triage desk", "一次受付"), "specialists": ("Specialists", "専門チーム"),
}
POD_OF = {"enterprise": "enterprise", "public": "public", "smb": "growth", "ai_startup": "growth"}
PRODUCT_OF = {"server": "server", "gpu": "gpu", "storage": "infra", "network": "infra"}
STAGES = ["qualify", "hearing", "sizing", "sizing2", "quote", "poc", "proposal", "followup"]
WEEK = 5


def clock(t):
    if t <= 0:
        return "Start"
    return "Week %d, day %d" % ((t - 1) // WEEK + 1, (t - 1) % WEEK + 1)


def stage_hours(deal, stage):
    """Work hours for a stage, before skill and tools. A typical deal is about 20 hours in total."""
    c = deal["complexity"]
    g = 1.4 if deal["domain"] == "gpu" else 1.0
    if stage == "qualify":
        return 1.0
    if stage == "hearing":
        return 2.0 * c
    if stage == "sizing":
        return 3.0 * c * g
    if stage == "sizing2":
        return 1.5 * c if deal["domain2"] else 0.0
    if stage == "quote":
        return 1.5 + 0.5 * c
    if stage == "poc":
        return 24.0 if deal["poc"] else 0.0
    if stage == "proposal":
        return 2.5 * c
    return 1.0


def stage_domain(deal, stage):
    if stage in ("qualify", "quote", "followup"):
        return None
    return deal["domain2"] if stage == "sizing2" else deal["domain"]


def assign_squads(state, org, rng):
    live = [m for m in state["members"] if not m["left"]]
    if org == "pool":
        for m in live:
            m["squad"] = "pool"
    elif org == "product_squads":
        for m in live:
            m["squad"] = PRODUCT_OF[m["primary"]]
    elif org == "account_pods":
        pods = ORG_SQUADS[org]
        order = sorted(live, key=lambda m: (["senior", "mid", "junior"].index(m["level"]), m["id"]))
        for i, m in enumerate(order):
            m["squad"] = pods[i % 3]
    else:
        juniors = [m for m in live if m["level"] == "junior"]
        desk = set(m["id"] for m in juniors[:max(1, int(round(len(live) * 0.17)))])
        for m in live:
            m["squad"] = "desk" if m["id"] in desk else "specialists"


def route(state, params, deal, stage):
    org = params["org_model"]
    if org == "pool":
        return "pool"
    if org == "product_squads":
        dom = stage_domain(deal, stage) or deal["domain"]
        return PRODUCT_OF[dom]
    if org == "account_pods":
        return POD_OF[deal["seg"]]
    if stage == "qualify":
        return "desk"
    easy = deal["complexity"] == 1 and deal["domain"] != "gpu"
    if easy and deal["squad"] == "desk":
        # the desk keeps simple deals unless it is already swamped
        desk_people = sum(1 for m in state["members"] if not m["left"] and m["squad"] == "desk")
        desk_work = sum(d["work_left"] for d in state["deals"] if d["squad"] == "desk")
        if desk_work < desk_people * 12.0:
            return "desk"
    return "specialists"


def new_member(state, level, primary, rng):
    top = LEVELS[level]["top"]
    skills = {}
    for d in DOMAINS:
        if d == primary:
            skills[d] = top
        else:
            skills[d] = max(0, top - 1 - (1 if rng.random() < 0.5 else 0))
    state["next_member"] += 1
    return {"id": "%s%d" % (level[0].upper(), state["next_member"]), "level": level, "primary": primary,
            "skills": skills, "squad": "pool", "fatigue": 0.1, "left": False, "util": 0.0, "joined": 0}


def init(params, rng):
    state = {
        "members": [], "next_member": 0, "deals": [], "next_deal": 0,
        "tool_on": bool(params["configurator"]), "pending": [],
        "policy": {
            "priority": "deadline", "wip_limit": 3,
            "members": {lv: {"normal": 0.8, "overtime": 0.1, "cut_corners": 0.05, "push_back": 0.05} for lv in LEVELS},
            "sales": {"wait": 0.7, "escalate": 0.2, "self_quote": 0.05, "drop": 0.05},
            "customers": {"wait": 0.7, "press": 0.2, "competitor": 0.1},
        },
        "budget": float(params["investment_budget"]), "dip_days": 0,
        "won": 0.0, "won_n": 0, "lost_n": 0, "lost_delay": 0, "dropped": 0, "self_quoted": 0,
        "closed": [], "handoffs": 0, "overtime_week": [], "today": {"util": 0.0, "hours": 0.0, "cap": 0.0},
        "ask_weekly": True, "ask_monthly": True, "left_count": 0,
    }
    n = int(params["team_size"])
    n_senior = max(1, int(round(n * 0.25)))
    n_junior = max(1, int(round(n * 0.30)))
    levels = ["senior"] * n_senior + ["mid"] * (n - n_senior - n_junior) + ["junior"] * n_junior
    # primaries follow demand roughly: server-heavy, some GPU, some storage/network
    wheel = ["server", "gpu", "storage", "server", "network", "gpu", "server", "storage"]
    for i, lv in enumerate(levels):
        state["members"].append(new_member(state, lv, wheel[i % len(wheel)], rng))
    assign_squads(state, params["org_model"], rng)
    return state


def arrivals(params, t):
    """Deals that arrive today. Depends only on the seed and the day, so every branch sees the same market."""
    exo = random.Random(params["_seed"] * 100003 + t)
    lam = params["deals_per_day"] * params["demand_factor"]
    n, p, L = 0, exo.random(), math.exp(-lam)
    while p > L and n < 30:
        n += 1
        p *= exo.random()
    out = []
    gshare = params["gpu_demand_share"]
    rest = max(0.0, 1.0 - gshare)
    for _ in range(n):
        r, seg, acc = exo.random(), "smb", 0.0
        for k, v in SEGMENTS.items():
            acc += v["share"]
            if r < acc:
                seg = k
                break
        r = exo.random()
        if seg == "ai_startup" and r < 0.75:
            dom = "gpu"
        elif r < gshare:
            dom = "gpu"
        elif r < gshare + rest * 0.53:
            dom = "server"
        elif r < gshare + rest * 0.80:
            dom = "storage"
        else:
            dom = "network"
        dom2 = None
        if exo.random() < 0.4:
            dom2 = exo.choice([d for d in DOMAINS if d != dom])
        r = exo.random()
        cx = 1 if r < (0.25 if dom == "gpu" else 0.45) else (2 if r < 0.8 else 3)
        size = SEGMENTS[seg]["size"] * math.exp(exo.gauss(0, 0.7)) * (2.0 if dom == "gpu" else 1.0)
        out.append({"seg": seg, "domain": dom, "domain2": dom2, "complexity": cx, "size": round(size, 1),
                    "poc": dom == "gpu" and size > 50 and exo.random() < 0.6,
                    "days": SEGMENTS[seg]["days"] + cx * 3, "u": exo.random(), "h": exo.random()})
    return out


def enter_stage(state, params, deal, t):
    """Move a deal to its next stage with work, handling routing, handoffs and the approval wait."""
    while deal["stage"] < len(STAGES):
        stage = STAGES[deal["stage"]]
        hours = stage_hours(deal, stage)
        if hours <= 0:
            deal["stage"] += 1
            continue
        if state["tool_on"] and stage in ("sizing", "sizing2", "quote"):
            hours /= 1.35
        squad = route(state, params, deal, stage)
        if deal["squad"] is not None and squad != deal["squad"]:
            deal["handoffs"] += 1
            state["handoffs"] += 1
            deal["wait_until"] = max(deal["wait_until"], t + 1)     # picked up the next day at the earliest
            hours += 1.0                                            # the new team has to read in
            deal["assignee"] = None
        deal["squad"] = squad
        deal["work_left"] = hours
        return
    deal["done"] = True


def close(state, params, deal, t, rng):
    late = max(0, t - deal["deadline"])
    quality = deal["q_sum"] / deal["h_sum"] if deal["h_sum"] > 0 else 0.6
    seg = SEGMENTS[deal["seg"]]
    timeliness = math.exp(-0.12 * late)
    if deal["seg"] == "public" and late > 0:
        timeliness = 0.0
    p = seg["win"] * (quality ** 1.5) / (0.92 ** 1.5) * timeliness
    if deal["poc"]:
        p *= 1.15
    if deal["pushed"]:
        p *= 0.95
    won = deal["u"] < min(0.95, p)
    if won:
        state["won"] += deal["size"] * 1e6
        state["won_n"] += 1
    else:
        state["lost_n"] += 1
    state["closed"] = (state["closed"] + [{"won": won, "lead": t - deal["arrived"], "late": late > 0, "q": quality}])[-40:]
    return won


def step(state, params, rng, t):
    events = []
    pol = state["policy"]
    org = params["org_model"]
    live = [m for m in state["members"] if not m["left"]]

    # ---- scheduled things arrive (hires, tools, training) ----
    still = []
    for item in state["pending"]:
        if t < item["at"]:
            still.append(item)
            continue
        if item["kind"] == "hire":
            primary = item.get("primary") or "gpu"
            m = new_member(state, item["level"], primary, rng)
            m["joined"] = t
            state["members"].append(m)
            assign_squads(state, org, rng)
            events.append({"kind": "info", "text": {
                "en": "A new %s engineer (%s) joins the department." % (item["level"], primary),
                "ja": "新しい %s エンジニア（%s）が加わった。" % ({"senior": "シニア", "mid": "中堅", "junior": "ジュニア"}[item["level"]], primary)}})
        elif item["kind"] == "tool":
            state["tool_on"] = True
            events.append({"kind": "milestone", "text": {"en": "The configuration tool goes live: sizing and quotes get about 35% faster.",
                                                         "ja": "構成ツールが使えるようになった。サイジングと見積もりが約 35% 速くなる。"},
                           "fact": {"subject": "department", "predicate": "configurator", "object": True}})
        elif item["kind"] == "training":
            juniors = [m for m in live if m["level"] == "junior"][:3]
            for m in juniors:
                m["skills"][m["primary"]] = min(3, m["skills"][m["primary"]] + 1)
            events.append({"kind": "info", "text": {"en": "Training finishes: %d juniors move up a skill level." % len(juniors),
                                                    "ja": "研修が終わり、ジュニア %d 人のスキルが 1 段上がった。" % len(juniors)}})
    state["pending"] = still
    live = [m for m in state["members"] if not m["left"]]

    # ---- new deals ----
    sales = pol["sales"]
    for a in arrivals(params, t):
        state["next_deal"] += 1
        if a["size"] < 5 and a["h"] < sales["drop"]:
            state["dropped"] += 1
            continue
        easy = a["complexity"] == 1 and a["domain"] != "gpu"
        if easy and a["h"] > 1 - sales["self_quote"]:
            # the sales rep quotes alone from a template: fast, but lower quality
            state["self_quoted"] += 1
            q = 0.8 if state["tool_on"] else 0.6
            p = SEGMENTS[a["seg"]]["win"] * (q ** 1.5) / (0.92 ** 1.5)
            if a["u"] < p:
                state["won"] += a["size"] * 1e6
                state["won_n"] += 1
            else:
                state["lost_n"] += 1
            continue
        deal = dict(a)
        deal.update({"id": state["next_deal"], "arrived": t, "deadline": t + a["days"], "stage": 0, "work_left": 0.0,
                     "squad": None, "assignee": None, "q_sum": 0.0, "h_sum": 0.0, "handoffs": 0, "wait_until": 0,
                     "pushed": False, "escalated": False, "done": False, "waited": 0})
        enter_stage(state, params, deal, t)
        state["deals"].append(deal)

    # ---- customers and sales react to waiting ----
    cust = pol["customers"]
    keep = []
    for d in state["deals"]:
        overdue = t - d["deadline"]
        if overdue > 0:
            if random.Random(params["_seed"] * 31 + d["id"] * 1009 + t).random() < cust["competitor"] * 0.05 * (1 + overdue / 5.0):
                state["lost_n"] += 1
                state["lost_delay"] += 1
                state["closed"] = (state["closed"] + [{"won": False, "lead": t - d["arrived"], "late": True, "q": 0.0}])[-40:]
                continue
        if d["deadline"] - t <= 3 and not d["escalated"] and d["h"] < sales["escalate"] + cust["press"] * 0.5:
            d["escalated"] = True
        keep.append(d)
    state["deals"] = keep

    # ---- today's capacity ----
    dip = 0.8 if state["dip_days"] > 0 else 1.0
    if state["dip_days"] > 0:
        state["dip_days"] -= 1
    n_esc = sum(1 for d in state["deals"] if d["escalated"])
    interrupt = min(1.5, 0.3 * n_esc / max(1, len(live)))           # hours each person loses to escalations
    hours, normal, used, load = {}, {}, {}, {}
    for m in live:
        mp = pol["members"][m["level"]]
        base = 8.0 * (1 - OVERHEAD[org]) * dip
        if t - m["joined"] < 20 and m["joined"] > 0:
            base *= 0.6                                              # newcomers are still learning the ropes
        normal[m["id"]] = base
        hours[m["id"]] = max(0.0, base + 2.0 * mp["overtime"] - interrupt)
        used[m["id"]] = 0.0
        load[m["id"]] = 0
    for d in state["deals"]:
        if d["assignee"] in load and d["wait_until"] <= t:
            load[d["assignee"]] += 1                                 # deals waiting for an approval do not block a person
    by_id = {m["id"]: m for m in live}

    # ---- dispatch work in priority order ----
    prio = pol["priority"]

    def key(d):
        esc = 0 if d["escalated"] else 1
        if prio == "fifo":
            return (esc, d["arrived"], d["id"])
        if prio == "big_deals":
            return (esc, -d["size"], d["id"])
        if prio == "quick_wins":
            return (esc, d["work_left"], d["id"])
        return (esc, d["deadline"], d["id"])

    wip = int(pol["wip_limit"])
    for d in sorted(state["deals"], key=key):
        if d["wait_until"] > t or d["done"]:
            continue
        stage = STAGES[d["stage"]]
        dom = stage_domain(d, stage)
        m = by_id.get(d["assignee"]) if d["assignee"] else None
        if m is not None and m["squad"] == d["squad"] and hours[m["id"]] < 0.25:
            d["waited"] += 1                                         # its engineer is busy today; the deal waits for them
            continue
        if m is None or m["squad"] != d["squad"]:
            cands = [x for x in live if x["squad"] == d["squad"] and hours[x["id"]] >= 0.25 and load[x["id"]] < wip]
            if not cands:
                d["waited"] += 1
                continue
            cands.sort(key=lambda x: (-(x["skills"][dom] if dom else 1), -hours[x["id"]], x["id"]))
            m2 = cands[0]
            if d["assignee"] != m2["id"]:
                if d["assignee"] in load:
                    load[d["assignee"]] -= 1
                load[m2["id"]] += 1
                hours[m2["id"]] -= 0.4                               # reading in costs time
                d["assignee"] = m2["id"]
            m = m2
        mp = pol["members"][m["level"]]
        skill = m["skills"][dom] if dom else 2
        sp = LEVELS[m["level"]]["speed"] * SKILL_SPEED[skill] * (1 - 0.35 * m["fatigue"]) * (1 + 0.2 * mp["cut_corners"])
        q = SKILL_QUALITY[skill] * (1 - 0.3 * m["fatigue"]) * (1 - 0.15 * mp["cut_corners"])
        h = max(0.0, min(hours[m["id"]], d["work_left"] / sp, 6.0))
        d["work_left"] -= h * sp
        hours[m["id"]] -= h
        used[m["id"]] += h
        d["q_sum"] += q * h
        d["h_sum"] += h
        if d["work_left"] <= 1e-6:
            if stage == "quote":
                d["wait_until"] = t + (3 if d["size"] > 100 else 2)   # internal price approval
            d["stage"] += 1
            enter_stage(state, params, d, t)
        if mp["push_back"] > 0 and not d["pushed"] and d["deadline"] - t <= 2 and d["h"] > 1 - mp["push_back"]:
            d["pushed"] = True
            d["deadline"] += 3

    # ---- finished deals get an answer from the customer ----
    keep = []
    for d in state["deals"]:
        if d["done"]:
            close(state, params, d, t, rng)
        else:
            keep.append(d)
    state["deals"] = keep

    # ---- fatigue and people leaving ----
    tot_used = tot_cap = ot = 0.0
    for m in live:
        mp = pol["members"][m["level"]]
        u = used[m["id"]] / normal[m["id"]] if normal[m["id"]] > 0 else 0.0
        m["util"] = u
        m["fatigue"] += 0.012 * mp["overtime"] + 0.02 * max(0.0, u - 0.9) - (0.008 if u < 0.8 else 0.0)
        m["fatigue"] = max(0.0, min(1.0, m["fatigue"]))
        tot_used += used[m["id"]]
        tot_cap += normal[m["id"]]
        ot += max(0.0, used[m["id"]] - normal[m["id"]])
        if rng.random() < 0.0004 + 0.004 * max(0.0, m["fatigue"] - 0.6) and len(live) > 3:
            m["left"] = True
            state["left_count"] += 1
            for d in state["deals"]:
                if d["assignee"] == m["id"]:
                    d["assignee"] = None
            events.append({"kind": "alert", "node": m["squad"], "text": {
                "en": "%s (%s, %s) resigns, worn out." % (m["id"], m["level"], m["primary"]),
                "ja": "%s（%s、%s）が疲れ切って退職した。" % (m["id"], {"senior": "シニア", "mid": "中堅", "junior": "ジュニア"}[m["level"]], m["primary"])}})
    state["overtime_week"] = (state["overtime_week"] + [ot])[-WEEK:]
    state["today"] = {"util": tot_used / tot_cap if tot_cap > 0 else 0.0, "hours": tot_used, "cap": tot_cap}
    if any(m["left"] for m in live):
        assign_squads(state, org, rng)

    state["ask_weekly"] = (t - 1) % WEEK == 0
    state["ask_monthly"] = (t - 1) % (WEEK * 4) == 0
    return events


def trailing(state):
    c = state["closed"]
    if not c:
        return {"win": 0.0, "lead": 0.0, "on_time": 100.0, "quality": 0.0}
    done = [x for x in c if x["q"] > 0]
    return {
        "win": sum(1 for x in c if x["won"]) / len(c) * 100,
        "lead": sum(x["lead"] for x in c) / len(c),
        "on_time": sum(1 for x in c if not x["late"]) / len(c) * 100,
        "quality": sum(x["q"] for x in done) / len(done) * 100 if done else 0.0,
    }


def squad_stats(state, squad):
    live = [m for m in state["members"] if not m["left"] and m["squad"] == squad]
    deals = [d for d in state["deals"] if d["squad"] == squad]
    return {
        "people": len(live), "open_deals": len(deals), "backlog_hours": round(sum(d["work_left"] for d in deals), 1),
        "utilisation_pct": round(sum(m["util"] for m in live) / len(live) * 100) if live else 0,
        "fatigue_pct": round(sum(m["fatigue"] for m in live) / len(live) * 100) if live else 0,
    }


def overview(state, params, t):
    tr = trailing(state)
    live = [m for m in state["members"] if not m["left"]]
    overdue = sum(1 for d in state["deals"] if t > d["deadline"])
    return {
        "day": clock(t), "team_structure": params["org_model"], "headcount": len(live),
        "open_deals": len(state["deals"]), "overdue_deals": overdue,
        "backlog_hours": round(sum(d["work_left"] for d in state["deals"])),
        "utilisation_pct": round(state["today"]["util"] * 100), "avg_fatigue_pct": round(sum(m["fatigue"] for m in live) / max(1, len(live)) * 100),
        "avg_days_to_answer": round(tr["lead"], 1), "on_time_pct": round(tr["on_time"]), "win_rate_pct": round(tr["win"]),
        "revenue_won_million_yen": round(state["won"] / 1e6), "configurator_tool": state["tool_on"],
        "people_who_left": state["left_count"],
    }


def decisions(state, params, t):
    reqs = []
    if not (state["ask_weekly"] or state["ask_monthly"]):
        return reqs
    O = overview(state, params, t)
    lead = ("Presales department for server hardware, %s. Team structure: %s. %d engineers, %d open deals (%d overdue), %d hours of work queued, "
            "utilisation %d%%, average fatigue %d%%. Recent deals: answered in %.1f days on average, %d%% on time, %d%% won."
            % (O["day"], O["team_structure"], O["headcount"], O["open_deals"], O["overdue_deals"], O["backlog_hours"],
               O["utilisation_pct"], O["avg_fatigue_pct"], O["avg_days_to_answer"], O["on_time_pct"], O["win_rate_pct"]))
    pol = state["policy"]
    if state["ask_weekly"]:
        reqs.append({
            "key": "manager", "agent": "manager", "node": "manager", "mode": "pick",
            "situation": lead + " Current rule: %s; each engineer handles at most %d deals at once." % (pol["priority"], pol["wip_limit"]),
            "facts": O, "question": "Which priority rule do you set for this week, and how many deals may one engineer handle at once?",
            "options": [
                {"id": "deadline", "label": {"en": "Nearest deadline first", "ja": "締め切りが近い順"}},
                {"id": "fifo", "label": {"en": "First come, first served", "ja": "来た順"}},
                {"id": "big_deals", "label": {"en": "Biggest deals first", "ja": "金額が大きい順"}},
                {"id": "quick_wins", "label": {"en": "Least remaining work first", "ja": "残りの作業が少ない順"}},
            ],
            "numbers": [{"id": "wip_limit", "label": {"en": "Deals per engineer at once", "ja": "1 人が同時に持つ案件数"}, "min": 1, "max": 6, "default": pol["wip_limit"]}],
            "default": {"choice": pol["priority"], "numbers": {"wip_limit": pol["wip_limit"]}},
        })
        for lv in LEVELS:
            people = [m for m in state["members"] if not m["left"] and m["level"] == lv]
            if not people:
                continue
            fat = round(sum(m["fatigue"] for m in people) / len(people) * 100)
            util = round(sum(m["util"] for m in people) / len(people) * 100)
            reqs.append({
                "key": "engineers:" + lv, "agent": lv + "_engineers", "node": people[0]["squad"], "mode": "split", "population": len(people),
                "situation": lead + " Your group: %d %s engineers, utilisation %d%%, fatigue %d%%." % (len(people), lv, util, fat),
                "facts": {"group_size": len(people), "utilisation_pct": util, "fatigue_pct": fat, "overdue_deals": O["overdue_deals"]},
                "question": "This week, how does your group split between these ways of coping with the workload?",
                "options": [
                    {"id": "normal", "label": {"en": "Work normal hours at normal care", "ja": "通常の時間、通常の丁寧さで働く"}},
                    {"id": "overtime", "label": {"en": "Work about 2 hours overtime a day", "ja": "1 日 2 時間ほど残業する"}},
                    {"id": "cut_corners", "label": {"en": "Go faster with less checking", "ja": "確認を減らして速く進める"}},
                    {"id": "push_back", "label": {"en": "Ask sales to move deadlines", "ja": "営業に締め切りの延長を頼む"}},
                ],
                "default": {"weights": {"normal": 0.8 - (0.3 if O["overdue_deals"] > 3 else 0.0), "overtime": 0.1 + (0.2 if O["overdue_deals"] > 3 else 0.0),
                                        "cut_corners": 0.05 + (0.05 if O["overdue_deals"] > 3 else 0.0), "push_back": 0.05 + (0.05 if O["overdue_deals"] > 3 else 0.0)}},
            })
        reqs.append({
            "key": "sales_reps", "agent": "sales_reps", "node": "sales", "mode": "split", "population": int(params["sales_reps"]),
            "situation": lead + " Sales reps wait about %.1f days for presales answers. So far %d deals were lost because the answer came too late."
            % (O["avg_days_to_answer"], state["lost_delay"]),
            "facts": O, "question": "This week, how do the sales reps split in how they deal with presales?",
            "options": [
                {"id": "wait", "label": {"en": "Wait in the queue", "ja": "順番を待つ"}},
                {"id": "escalate", "label": {"en": "Escalate to jump the queue", "ja": "上にかけ合って割り込む"}},
                {"id": "self_quote", "label": {"en": "Quote simple deals alone from a template", "ja": "簡単な案件はテンプレートで自分で見積もる"}},
                {"id": "drop", "label": {"en": "Stop bringing small deals", "ja": "小さい案件は持ち込まない"}},
            ],
            "default": {"weights": {"wait": 0.7 - (0.25 if O["avg_days_to_answer"] > 10 else 0.0), "escalate": 0.2 + (0.15 if O["avg_days_to_answer"] > 10 else 0.0),
                                    "self_quote": 0.05 + (0.05 if O["avg_days_to_answer"] > 10 else 0.0), "drop": 0.05 + (0.05 if O["avg_days_to_answer"] > 10 else 0.0)}},
        })
        reqs.append({
            "key": "customers", "agent": "customers", "node": "won", "mode": "split", "population": max(1, O["open_deals"]),
            "situation": "Customers buying servers have %d requests open with this vendor; %d are past the promised date. Recent answers took %.1f days and %d%% arrived on time."
            % (O["open_deals"], O["overdue_deals"], O["avg_days_to_answer"], O["on_time_pct"]),
            "facts": {"open_deals": O["open_deals"], "overdue_deals": O["overdue_deals"], "on_time_pct": O["on_time_pct"]},
            "question": "Among customers whose answer is late, how do they split this week?",
            "options": [
                {"id": "wait", "label": {"en": "Wait patiently", "ja": "静かに待つ"}},
                {"id": "press", "label": {"en": "Press the sales rep hard", "ja": "営業に強く催促する"}},
                {"id": "competitor", "label": {"en": "Start talking to a competitor", "ja": "他社に声をかけ始める"}},
            ],
            "default": {"weights": {"wait": 0.7, "press": 0.2, "competitor": 0.1}},
        })
    if state["ask_monthly"]:
        opts = [
            {"id": "nothing", "label": {"en": "Change nothing this month", "ja": "今月は何も変えない"}},
            {"id": "hire_junior", "label": {"en": "Hire a junior (6M yen, starts in 4 weeks)", "ja": "ジュニアを 1 人採用（600 万円、4 週間後に着任）"}},
            {"id": "hire_senior", "label": {"en": "Hire a senior (14M yen, starts in 8 weeks)", "ja": "シニアを 1 人採用（1,400 万円、8 週間後に着任）"}},
            {"id": "training", "label": {"en": "Train three juniors (3M yen, 6 weeks)", "ja": "ジュニア 3 人を研修（300 万円、6 週間）"}},
        ]
        if not state["tool_on"] and not any(p["kind"] == "tool" for p in state["pending"]):
            opts.append({"id": "configurator", "label": {"en": "Build a configuration tool (20M yen, 6 weeks)", "ja": "構成ツールを作る（2,000 万円、6 週間）"}})
        if params["allow_reorg"]:
            for o in ORG_SQUADS:
                if o != params["org_model"]:
                    opts.append({"id": "reorg_" + o, "label": {"en": "Reorganise into: " + o, "ja": "組織を変更：" + o}})
        per_squad = {s: squad_stats(state, s) for s in ORG_SQUADS[params["org_model"]]}
        reqs.append({
            "key": "department_head", "agent": "department_head", "node": "head", "mode": "pick",
            "situation": lead + " Budget left: %d million yen. Squads: %s. %d people have left so far." % (round(state["budget"] / 1e6), per_squad, state["left_count"]),
            "facts": O, "question": "What one thing do you do this month?", "options": opts, "default": {"choice": "nothing"},
        })
    state["ask_weekly"] = False
    state["ask_monthly"] = False
    return reqs


def norm(weights, keys):
    w = {k: max(0.0, float(weights.get(k, 0.0))) for k in keys}
    tot = sum(w.values()) or 1.0
    return {k: v / tot for k, v in w.items()}


def do_reorg(state, params, org, t, rng):
    params["org_model"] = org
    assign_squads(state, org, rng)
    state["dip_days"] = 5
    for d in state["deals"]:
        d["squad"] = route(state, params, d, STAGES[d["stage"]])
        d["assignee"] = None
    return [{"kind": "intervention", "text": {"en": "The department is reorganised into '%s'. Expect a slow week while people settle." % org,
                                              "ja": "部署を「%s」に組み替えた。落ち着くまで 1 週間ほど遅くなる。" % org},
             "fact": {"subject": "department", "predicate": "team_structure", "object": org}}]


def apply(state, params, rng, t, action):
    pol, key = state["policy"], action["key"]
    if key == "manager":
        pol["priority"] = action.get("choice") or pol["priority"]
        pol["wip_limit"] = int(round((action.get("numbers") or {}).get("wip_limit", pol["wip_limit"])))
    elif key.startswith("engineers:"):
        pol["members"][key.split(":")[1]] = norm(action["weights"], ["normal", "overtime", "cut_corners", "push_back"])
    elif key == "sales_reps":
        pol["sales"] = norm(action["weights"], ["wait", "escalate", "self_quote", "drop"])
    elif key == "customers":
        pol["customers"] = norm(action["weights"], ["wait", "press", "competitor"])
    elif key == "department_head":
        c = action.get("choice")
        cost = {"hire_junior": 6e6, "hire_senior": 14e6, "training": 3e6, "configurator": 20e6}.get(c, 0.0)
        if cost > state["budget"]:
            return None
        state["budget"] -= cost
        if c == "hire_junior":
            state["pending"].append({"kind": "hire", "level": "junior", "at": t + 20, "primary": busiest_domain(state)})
        elif c == "hire_senior":
            state["pending"].append({"kind": "hire", "level": "senior", "at": t + 40, "primary": busiest_domain(state)})
        elif c == "training":
            state["pending"].append({"kind": "training", "at": t + 30})
        elif c == "configurator":
            state["pending"].append({"kind": "tool", "at": t + 30})
        elif c and c.startswith("reorg_") and params["allow_reorg"]:
            return do_reorg(state, params, c[6:], t, rng)
        if cost > 0:
            return [{"kind": "info", "node": "head", "text": {"en": "The department head decides: %s." % c, "ja": "部長の決定：%s。" % c}}]
    return None


def busiest_domain(state):
    work = {d: 0.0 for d in DOMAINS}
    for d in state["deals"]:
        work[d["domain"]] += d["work_left"] + 1.0
    return max(work, key=lambda k: work[k])


def on_params(state, params, patch, t):
    rng = random.Random(params["_seed"] * 17 + t)
    events = []
    if "org_model" in patch:
        events += do_reorg(state, params, patch["org_model"], t, rng)
    if patch.get("configurator") and not state["tool_on"]:
        state["pending"].append({"kind": "tool", "at": t + 1})
    if patch.get("extra_seniors"):
        for _ in range(int(patch["extra_seniors"])):
            state["pending"].append({"kind": "hire", "level": "senior", "at": t + 1, "primary": busiest_domain(state)})
        params["extra_seniors"] = 0
    if patch.get("lose_senior"):
        seniors = [m for m in state["members"] if not m["left"] and m["level"] == "senior"]
        if seniors:
            m = max(seniors, key=lambda x: sum(x["skills"].values()))
            m["left"] = True
            state["left_count"] += 1
            for d in state["deals"]:
                if d["assignee"] == m["id"]:
                    d["assignee"] = None
            assign_squads(state, params["org_model"], rng)
            events.append({"kind": "alert", "text": {"en": "The most experienced senior (%s, %s) leaves for a competitor." % (m["id"], m["primary"]),
                                                     "ja": "一番経験のあるシニア（%s、%s）が競合に転職した。" % (m["id"], m["primary"])}})
        params["lose_senior"] = False
    state["ask_weekly"] = True
    return events


def metrics(state, params, t):
    tr = trailing(state)
    live = [m for m in state["members"] if not m["left"]]
    decided = state["won_n"] + state["lost_n"]
    return {
        "revenue_won": round(state["won"]), "win_rate": round(tr["win"], 1), "lead_time": round(tr["lead"], 2),
        "on_time": round(tr["on_time"], 1), "quality": round(tr["quality"], 1),
        "open_deals": len(state["deals"]), "backlog_hours": round(sum(d["work_left"] for d in state["deals"]), 1),
        "utilisation": round(state["today"]["util"] * 100, 1),
        "fatigue": round(sum(m["fatigue"] for m in live) / max(1, len(live)) * 100, 1),
        "overtime_hours": round(sum(state["overtime_week"]), 1), "headcount": len(live),
        "lost_to_delay": state["lost_delay"], "handoffs": state["handoffs"],
        "win_rate_total": round(state["won_n"] / decided * 100, 1) if decided else 0.0,
    }


def view(state, params, t):
    org = params["org_model"]
    squads = ORG_SQUADS[org]
    nodes, links = [], []
    incoming = len([d for d in state["deals"] if d["stage"] <= 1])
    nodes.append({"id": "sales", "label": {"en": "Sales reps", "ja": "営業"}, "x": 10, "y": 50, "value": incoming, "max": 20,
                  "sub": {"en": "%d new requests in hand" % incoming, "ja": "新しい依頼 %d 件" % incoming}, "status": "ok"})
    nodes.append({"id": "manager", "label": {"en": "Presales manager", "ja": "プリセールスのマネージャー"}, "x": 30, "y": 12, "value": state["policy"]["wip_limit"], "max": 6,
                  "sub": {"en": "rule: %s" % state["policy"]["priority"], "ja": "ルール：%s" % state["policy"]["priority"]}, "status": "ok"})
    nodes.append({"id": "head", "label": {"en": "Department head", "ja": "部長"}, "x": 62, "y": 10, "value": max(0.0, state["budget"]), "max": max(1.0, params["investment_budget"]),
                  "sub": {"en": "budget %dM yen" % round(state["budget"] / 1e6), "ja": "予算 %d 百万円" % round(state["budget"] / 1e6)}, "status": "ok"})
    for i, s in enumerate(squads):
        st = squad_stats(state, s)
        y = 50 if len(squads) == 1 else 28 + i * (52.0 / (len(squads) - 1))
        status = "crit" if st["fatigue_pct"] > 60 else ("warn" if st["utilisation_pct"] > 95 or st["fatigue_pct"] > 40 else "ok")
        nodes.append({"id": s, "label": {"en": SQUAD_LABEL[s][0], "ja": SQUAD_LABEL[s][1]}, "x": 46, "y": y,
                      "value": st["backlog_hours"], "max": 200, "status": status,
                      "sub": {"en": "%d people, %d deals, %dh queued, fatigue %d%%" % (st["people"], st["open_deals"], st["backlog_hours"], st["fatigue_pct"]),
                              "ja": "%d 人、案件 %d、残り %d 時間、疲労 %d%%" % (st["people"], st["open_deals"], st["backlog_hours"], st["fatigue_pct"])}})
        links.append({"a": "sales", "b": s, "value": st["open_deals"], "max": 25})
        links.append({"a": s, "b": "won", "value": st["people"], "max": 14})
    nodes.append({"id": "won", "label": {"en": "Customers: deals won", "ja": "お客さま：受注"}, "x": 84, "y": 36, "value": state["won_n"], "max": 150,
                  "sub": {"en": "%d won, %dM yen" % (state["won_n"], round(state["won"] / 1e6)), "ja": "受注 %d 件、%d 百万円" % (state["won_n"], round(state["won"] / 1e6))}, "status": "ok"})
    nodes.append({"id": "lost", "label": {"en": "Deals lost", "ja": "失注"}, "x": 84, "y": 72, "value": state["lost_n"], "max": 150,
                  "sub": {"en": "%d lost (%d because we were late)" % (state["lost_n"], state["lost_delay"]), "ja": "失注 %d 件（うち遅れが原因 %d）" % (state["lost_n"], state["lost_delay"])},
                  "status": "warn" if state["lost_delay"] > 5 else "ok"})
    links.append({"a": "sales", "b": "lost", "value": state["lost_delay"], "max": 30})
    ja = "開始" if t <= 0 else "第 %d 週 %d 日目" % ((t - 1) // WEEK + 1, (t - 1) % WEEK + 1)
    return {"clock": {"en": clock(t), "ja": ja}, "nodes": nodes, "links": links}


def invariants(state, params, t):
    bad = []
    squads = set(ORG_SQUADS[params["org_model"]])
    for m in state["members"]:
        if not m["left"] and m["squad"] not in squads:
            bad.append("member %s is in unknown squad %s" % (m["id"], m["squad"]))
        if not 0.0 <= m["fatigue"] <= 1.0:
            bad.append("fatigue out of range")
    for d in state["deals"]:
        if d["work_left"] < -1e-6:
            bad.append("negative work on deal %d" % d["id"])
        if d["squad"] not in squads:
            bad.append("deal %d routed to unknown squad %s" % (d["id"], d["squad"]))
    return bad[:3]
