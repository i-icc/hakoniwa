"""Tick 1 settles Mon 2–Sun 8 March (week 0); news/reviews are at Sunday close.
Pending instructions are executed on the next personal account-check day. Daily
accounting splits boundary weeks; metrics never use a future simulated session.
All numerical mechanics not attributed in the recipe/spec are assumptions.
"""
import random
import math

PRODUCTS = ["sport", "virtual", "slots", "casino", "poker"]
KEYS = PRODUCTS + ["bets", "spins"]
COLS = ["real_event_active_idx", "virtual_active_idx", "slots_active_idx",
        "other_gaming_active_idx", "poker_active_idx", "real_event_bets_idx", "slots_bets_idx"]
START = [-1, 30, 60, 91, 121, 152]
MONTH = ["March", "April", "May", "June", "July", "August"]


def bi(en, ja):
    return {"en": en, "ja": ja}


def month(day):
    return sum(day >= n for n in START) - 1


def stage(d, p):
    a = p["advance"]
    return (int(d >= 11) + int(d >= 16) + int(d >= 21) +
            int(d >= 75-a) + int(d >= 91-a) + int(d >= 107-a) +
            int(d >= 121) + int(d >= 147))


def menu(d, p, h):
    a = p["advance"]
    football = (1 if d < 11 else 0.20 if d >= 147 else
                1.55 if d >= 121 else 1 if d >= 107-a else 0.46 if d >= 75-a else 0)
    racing = 1.8 if 8 <= d <= 11 else int(d < 16 or d >= 91-a)
    f, r = h["football_weight"], h["racing_weight"]
    return f*football + r*racing + (1-f-r)*0.85


def income(h, d, p):
    u = h["work_rank"]
    lost = 0.0396
    furl = 0.078 if h["sex"] == "man" else 0.115
    steady = 0.631 if h["sex"] == "man" else 0.601
    if u >= lost + furl + steady:
        return "outside continuing employment", 1
    if d < 21:
        return "working", 1
    if u < lost:
        return "lost work", 0.35
    if u < lost + furl*p["furlough"]:
        return "furloughed", 0.75
    return "working", 1


def init(params, rng):
    people = []
    for h in params["_data"]["bettors"]:
        rates = ([0.030,0.109,0.118,0.070] if h["sex"] == "man"
                 else [0.043,0.126,0.085,0.041])
        prior = [k for k,rate in zip(PRODUCTS[1:], rates) if rng.random() < rate]
        former = rng.random() < params["former"]
        people.append(dict(winter_products=prior, never_slots="slots" not in prior and not former,
                           monthly_sports_pounds=h["band"]*h["variation"],
                           plan="sport", multiplier=1, pending=None, reviews=0, last_review=0,
                           known_stage=0, reason="", offer_seen=False, offer_this_week=False,
                           first_slot_month=-1, august_repeat=False, wallet=0, wanted=0, staked=0,
                           total_staked=0, cash_used=0, cash_limit=0, known_work=income(h,0,params)[0],
                           active_masks=[0]*6, april_inactive=False, july_return=False))
    return dict(people=people, months=[dict.fromkeys(KEYS+["wanted","staked"],0) for _ in START],
                ask=[], week=0)


def options():
    labels=[("keep","Carry on exactly as before","今の方針のまま"),
            ("sport","Use my ordinary sports routine","普段の競技の習慣にする"),
            ("stop","Stop all play and keep the money","全て休んでお金を残す"),
            ("unfamiliar","Use unfamiliar real events instead","不慣れな実競技を選ぶ"),
            ("virtual","Use virtual sports instead","仮想競技を選ぶ"),
            ("slots","Use slots instead","スロットを選ぶ"),
            ("casino","Use other casino games instead","他のカジノゲームを選ぶ"),
            ("poker","Use poker instead","ポーカーを選ぶ")]
    return [dict(id=i,label=bi(e,j)) for i,e,j in labels]


def settle(s, p, h, b, d, draw):
    m = month(d)
    book = s["months"][m]
    if b["pending"]:
        new, factor = b["pending"]
        b.update(plan=new, multiplier=factor, pending=None)
    plan=b["plan"]
    if plan=="stop":
        return
    gap=h["gap"]
    ordinary=b["monthly_sports_pounds"]*gap/30.44
    # Stochastic rounding is the spacing of ordinary betting occasions, not
    # an extra compliance probability. Deliberate substitutes schedule a session.
    ticket=min(5, max(0.5, ordinary))
    expected=ordinary*b["multiplier"]/ticket
    n=int(expected)+(draw.random()<expected%1)
    weights=menu(d,p,h)
    jobs=[]
    if plan in ("sport","unfamiliar"):
        supply=weights if plan=="sport" else 0.85
        jobs.append(("sport",n,ticket,supply*p["live_supply"],1,0.09))
    else:
        unit={"slots":1.05 if h["age"]=="18–24" else 1.30,
              "virtual":2,"poker":2,"casino":2}[plan]
        count=int(max(1,ordinary/unit)*b["multiplier"]*(8 if plan=="slots" else 2))
        jobs.append((plan,count,unit,1,0.12 if plan=="slots" else 2,0.06))
    # Winter participation is eligibility for a parallel routine, not frequency.
    for k in b["winter_products"]:
        if k!=plan and draw.random()<0.32:
            unit=(1.05 if h["age"]=="18–24" else 1.30) if k=="slots" else 2
            count=int((12 if k=="slots" else 3)*b["multiplier"])
            jobs.append((k,count,unit,1,0.12 if k=="slots" else 2,0.06))
    time=h["session_minutes"]*p["minutes"]
    for k,n,unit,supply,mins,loss in jobs:
        # Congestion adds opportunities; cancellations remove them only after
        # recording the customer's desired volume at this account check.
        want=n*max(1,supply)
        want=int(want)+(draw.random()<want%1)
        asked=want*unit
        book["wanted"]+=asked
        b["wanted"]+=asked
        available=want*min(1,supply)
        available=int(available)+(draw.random()<available%1)
        # Pay full first stake, recycle deterministic expected returns thereafter.
        affordable=0 if b["wallet"]+1e-9<unit else 1+int((b["wallet"]-unit+1e-9)/(unit*loss))
        got=min(available,affordable,int(time/mins))
        if got<=0:
            continue
        amount=got*unit
        time-=got*mins
        b["wallet"]-=amount*loss
        b["cash_used"]+=amount*loss
        b["staked"]+=amount
        b["total_staked"]+=amount
        book["staked"]+=amount
        bit=1<<PRODUCTS.index(k)
        if not (b["active_masks"][m]&bit):
            book[k]+=1
            b["active_masks"][m]|=bit
        if k=="sport":
            book["bets"]+=got
        if k=="slots":
            book["spins"]+=got
            if b["never_slots"] and b["first_slot_month"]<0:
                b["first_slot_month"]=m
            if m==5 and 0<=b["first_slot_month"]<5:
                b["august_repeat"]=True


def step(state,params,rng,t):
    start=7*(t-1)
    end=start+6
    state.update(ask=[],week=t)
    exo=random.Random(params["_seed"]*100003+t)
    for i,(h,b) in enumerate(zip(params["_data"]["bettors"],state["people"])):
        heard,mail=exo.random(),exo.random()
        draw=random.Random(exo.getrandbits(64))
        work,factor=income(h,start,params)
        cap=(4+b["monthly_sports_pounds"]/12)*factor*params["liquidity"]
        b.update(wallet=cap,cash_limit=cap,cash_used=0,wanted=0,staked=0)
        visited=False
        last_seen=b["known_stage"]
        for d in range(start,end+1):
            if (d-h["phase"])%h["gap"]==0:
                visited=True
                last_seen=stage(d,params)
                settle(state,params,h,b,d,draw)
        b["april_inactive"]=end>=59 and b["active_masks"][1]==0
        b["july_return"]=b["april_inactive"] and bool(b["active_masks"][4]&1)
        notices=[]
        if heard < h["news_reach"]:
            last_seen=stage(end,params)
        if last_seen!=b["known_stage"]:
            notices.append("a change in the fixture listings")
            b["known_stage"]=last_seen
        if work!=b["known_work"]:
            notices.append("your employment changed")
            b["known_work"]=work
        b["offer_this_week"]=params["offers"] and mail<params["reach"] and t>=3
        if b["offer_this_week"] and not b["offer_seen"]:
            notices.append("your first casino promotion this run")
            b["offer_seen"]=True
        if not notices and (b["plan"]!="sport" or b["known_stage"] in (2,3,4)) and t-b["last_review"]>=params["review"]:
            notices.append("time to review your routine")
        b["reason"]=", ".join(notices)
        if notices and b["reviews"]<params["max_asks"] and t<26:
            state["ask"].append(i)
    dates=[(8,"Cheltenham Festival, 10–13 March","3月10～13日、チェルトナム開催"),
           (11,"English football suspended","イングランドのサッカー中断"),
           (16,"British racing stopped","英国競馬が中断"),
           (21,"National lockdown begins","全国的な外出制限開始"),
           (75-params["advance"],"German football returns","ドイツのサッカー再開"),
           (91-params["advance"],"British racing returns","英国競馬再開"),
           (107-params["advance"],"Premier League returns","プレミアリーグ再開"),
           (121,"Packed July football calendar","7月のサッカー日程が過密に"),
           (147,"League season over; fewer matches","リーグ戦終了、試合減少")]
    return [dict(kind="milestone",text=bi(e,j)) for d,e,j in dates if start<=d<=end]


def rule(h,b):
    scarce=b["known_stage"] in (2,3,4)
    plan=b["pending"][0] if b["pending"] else b["plan"]
    choice="keep"
    if scarce and plan=="sport":
        if h["curiosity"]>0.94 or (b["offer_this_week"] and h["curiosity"]>0.82):
            choice=("slots" if b["offer_this_week"] else h["alternative"])
        elif b["known_work"]=="lost work" and h["caution"]>0.55:
            choice="stop"
    if b["known_stage"]>=5 and plan!="sport" and h["curiosity"]<0.97:
        choice="sport"
    return dict(choice=choice,numbers={"factor":b["pending"][1] if b["pending"] else b["multiplier"]})


def decisions(state,params,t):
    requests=[]
    for i in state["ask"]:
        h=params["_data"]["bettors"][i]
        b=state["people"][i]
        b["reviews"]+=1
        b["last_review"]=t
        d=7*t-1
        date=("Sunday close, week %d"%(t-1) if params["blind"] else
              "Sunday %d %s 2020, Great Britain"%(d-START[month(d)]+1,MONTH[month(d)]))
        stages=["ordinary fixtures","domestic football suspended; racing still running",
                "domestic football and racing suspended","stay-at-home restrictions; familiar fixtures absent",
                "a foreign football league back","domestic racing back, foreign football on",
                "the domestic football league back","a busy domestic football calendar",
                "the league season over, a quieter football calendar"]
        st=b["known_stage"]
        listing=stages[st]
        if st in (2,3):
            listing+=("; minor overseas football, table tennis, esports and virtual sports listed" if params["blind"]
                      else "; Belarusian football, table tennis, esports and virtual sports listed")
        plan,fac=b["pending"] or (b["plan"],b["multiplier"])
        sit=("%s. Reason for review: %s. Your latest fixture information: %s. Work: %s. "
             "Your winter gaming products: %s. Your current instruction is %s at %.2f times usual size. "
             "This week you wanted £%.2f in stakes and actually turned over £%.2f including re-used returns. "
             "£%.2f of your £%.2f leisure cash is left to keep. Your usual session has %d minutes; "
             "trying something else takes time and risks money you could keep. A missed fixture costs no stake. %s"%
             (date,b["reason"],listing,b["known_work"],", ".join(b["winter_products"]) or "none",plan,fac,
              b["wanted"],b["staked"],b["wallet"],b["cash_limit"],h["session_minutes"],
              "You noticed a sports-account message promoting casino games this week." if b["offer_this_week"]
              else "No new casino offer noticed this week."))
        requests.append(dict(key="bettor:%d"%i,agent="bettor",name=h["name"],mode="pick",
            persona="%s; %s; %s; %s. Curiosity %.2f, financial caution %.2f. %s"%
                    (h["sex"],h["age"],h["kind"],h["news"],h["curiosity"],h["caution"],h["story"]),
            situation=sit,facts=dict(usual_monthly_sports_turnover=round(b["monthly_sports_pounds"],2),
                                     days_between_checks=h["gap"],cash_left=round(b["wallet"],2)),
            question="At your next account check, what, if anything, do you change? You can leave your instruction and amount exactly as they are.",
            options=options(),numbers=[dict(id="factor",label=bi("Stake volume relative to usual","普段に対する賭け金総額の倍率"),
                                           min=0,max=3,default=fac)],default=rule(h,b)))
    return requests


def apply(state,params,rng,t,action):
    b=state["people"][int(action["key"].split(":")[1])]
    old,fac=b["pending"] or (b["plan"],b["multiplier"])
    choice=action.get("choice","keep")
    b["pending"]=[choice if choice in PRODUCTS+["unfamiliar","stop"] else old,
                  max(0,min(3,float((action.get("numbers") or {}).get("factor",fac))))]


def metrics(state,params,t):
    m=month(max(0,7*(t-1)))
    base,now=state["months"][0],state["months"][m]
    rows=params["_data"].get("reference",[])
    row=rows[t-1] if 1<=t<=len(rows) else {}
    out={}
    for k,col in zip(KEYS,COLS):
        out[k]=round(100*now[k]/base[k],2) if base[k] else 0
        out["real_"+k]=float(row.get(col,0))
    return out


def view(state,params,t):
    d=max(0,7*(t-1))
    m=month(d)
    people=state["people"]
    book=state["months"][m]
    nodes=[]
    def node(k,e,j,x,y,v,cap,sub=None):
        n=dict(id=k,label=bi(e,j),x=x,y=y,value=v,max=max(1,cap))
        if sub:
            n["sub"]=sub
        nodes.append(n)
    node("people","Winter sports bettors","冬のスポーツ客",10,50,len(people),len(people))
    for i,(k,j) in enumerate(zip(PRODUCTS,["実競技","仮想競技","スロット","他のカジノ","ポーカー"])):
        node(k,k.title(),j,45,10+19*i,book[k],len(people))
    started=sum(b["first_slot_month"]>=0 for b in people)
    repeat=sum(b["august_repeat"] for b in people)
    node("start","First-ever slot players to date","初スロット累計",84,22,started,len(people))
    node("repeat","Pre-Aug starters back in August","8月前の新規客の8月再利用",84,46,repeat,started)
    node("money","Month's turnover (£)","月間賭け金（ポンド）",84,76,round(book["staked"],2),book["wanted"],
         bi("Wanted £%.2f / staked £%.2f"%(book["wanted"],book["staked"]),
            "希望 £%.2f／実額 £%.2f"%(book["wanted"],book["staked"])))
    return dict(clock=bi("Week %d · %s to date"%(max(0,t-1),MONTH[m]),"第%d週・%d月累計"%(max(0,t-1),m+3)),
                nodes=nodes,links=[dict(a="people",b=k,value=book[k],max=len(people)) for k in PRODUCTS])


def invariants(state,params,t):
    people=state["people"]
    for b in people:
        if min(b["wallet"],b["cash_used"],b["wanted"]-b["staked"]) < -1e-6:
            return ["Negative cash or turnover above requested stakes"]
        if abs(b["cash_used"]+b["wallet"]-b["cash_limit"])>1e-6:
            return ["Wallet does not balance"]
        if b["august_repeat"] and not (b["never_slots"] and 0<=b["first_slot_month"]<5 and b["active_masks"][5]&4):
            return ["Invalid August retention flag"]
    for m,book in enumerate(state["months"]):
        for i,k in enumerate(PRODUCTS):
            if book[k]!=sum(bool(b["active_masks"][m]&(1<<i)) for b in people):
                return ["Monthly participation count mismatch"]
    if abs(sum(b["total_staked"] for b in people)-sum(v["staked"] for v in state["months"]))>0.001:
        return ["Turnover ledger mismatch"]
    return []