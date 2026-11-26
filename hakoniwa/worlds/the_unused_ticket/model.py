"""Tick t settles day d=t-1 (Feb 17 = 0); metrics and reference row are both for d.
Briefings are at the end of d; instructions are executed no earlier than d+1.
The baseline is a frozen manifest, independent of the observer's table.
"""
import random

def bi(en, ja):
    return {"en":en,"ja":ja}

def date(d):
    if d < 13:
        return "Feb %d" % (17+d)
    if d < 44:
        return "Mar %d" % (d-12)
    if d < 74:
        return "Apr %d" % (d-43)
    return "day %d" % d

def clip(x):
    return max(0,min(1,x))

def price(p,d,m):
    f=clip((d-13)/21)
    return round(m["factor"]*((1-f)*p["fare"]+f*p["lowfare"]))

def live(m):
    return m["status"] in ("idea","ticket")

def init(params,rng):
    p=params
    cast=p["_data"]["travellers"]
    n=len(cast)
    dates=[i%70 for i in range(n)]
    rng.shuffle(dates)
    spring=["student","spring break"]
    pool=[i for i,h in enumerate(cast) if h["purpose"] not in spring and 20<=dates[i]<=34]
    rng.shuffle(pool)
    for i,h in enumerate(cast):
        if h["purpose"] in spring and rng.random()<p["break_share"] and not 20<=dates[i]<=34 and pool:
            j=pool.pop()
            dates[i],dates[j]=dates[j],dates[i]
    normal=[[0]*3 for _ in range(70)]
    persons=[]
    for i,h in enumerate(cast):
        d=dates[i]
        route=sum(normal[d])%3
        normal[d][route]+=1
        purchase=d-rng.randint(1,2*p["lead"]-1)
        close=rng.random()<p["close_news"]
        business=h["purpose"]=="business"
        age=h["age"] if h["purpose"]!="student" else min(h["age"],27)
        m=dict(orig=d,due=d,route=route,buy=purchase,status="ticket" if purchase<0 else "idea",
               factor=rng.uniform(.72,1.28),ref=rng.random()<p["refund"]+.27*business,
               age=age,concern=rng.random()<.23+.10*clip((age-29)/36),
               delay=rng.randint(0,1) if close else rng.randint(2,6),
               employer=rng.random(),exception=rng.random()<.53/.84,
               essential=business and rng.random()<.15,meeting=business and rng.random()<.28,
               local=31+rng.randint(0,14),campus=22+rng.randint(0,5),
               creditable=rng.random()<.55,asked=0,last=-100,heard=[],fresh=[],
               plan="keep",held=False,lastmove=-100,paid=0,fees=0,returned=0,spent=0)
        fare=price(p,purchase,m)
        reserve=rng.randint(400,1600) if rng.random()<p["buffer_share"] else rng.randint(40,399)
        m["initial"]=round(p["fare"]*m["factor"])+reserve
        m["cash"]=m["initial"]
        if purchase<0:
            m.update(paid=fare,spent=fare,cash=m["cash"]-fare)
        persons.append(m)
    return {"people":persons,"ordinary":normal,"ask":[],"daily":blank()}

def blank():
    return dict(wanted=0,flew=0,seats=0,bookings=0,forced=0,dropped=0,moved=0)

# Public information and its generic blind equivalent.
NEWS={
 "death":("The first domestic death from coronavirus has been reported.","A first local death from the illness has been reported.","国内初の死亡が報じられた。"),
 "meeting":("A major festival was cancelled; conferences are being called off.","Large gatherings are being called off.","大型催事・会議の中止が広がる。"),
 "global":("WHO declared a pandemic, travel from Europe is being restricted, and a major sports league stopped play.","Health warnings have widened, some border travel is restricted and games are suspended.","パンデミック宣言、欧州からの渡航制限発表、スポーツ中断。"),
 "emergency":("A national emergency was declared.","Authorities issued an emergency declaration.","非常事態が宣言された。"),
 "advice":("Federal guidance asks people to avoid discretionary travel for 15 days.","Authorities advise against optional travel for a limited period.","不要な旅行を15日間避けるよう勧告。"),
 "abroad":("The State Department advises against travel abroad; California ordered residents to stay home.","Foreign travel is discouraged; a large region has ordered residents to stay home.","海外渡航中止勧告と州の外出制限。"),
 "local":("Your area is now under a stay-home order, with essential exceptions.","Your area now restricts nonessential outings.","居住地域でも不要な外出が制限された。"),
 "air":("Airlines are thinning schedules; tickets are selling more cheaply.","Fewer services are listed and fares have fallen.","航空会社の減便が進み運賃が下落。"),
 "fare":("Fares have fallen.","Ticket prices are lower.","運賃が下落。"),
 "campus":("Your campus asks you to leave within six days; your trip is now a journey home.","Your school asks you to leave within six days; this trip now takes you home.","大学から6日以内の退去通知。"),
 "expiry":("The original 15-day advice period has elapsed; that alone does not lift local orders.","The initial advice period is over; local restrictions are separate.","当初の勧告期間が終了。地域の命令とは別。")
}

def public(p):
    a=[(12,"death"),(18,"meeting"),(23,"global"),(int(p["emergency"]),"emergency"),(31,"abroad"),
       (36,"air" if p["cuts"] else "fare")]
    if p["guidance"]:
        a.extend([(28,"advice"),(43,"expiry")])
    return a

def fee(m):
    if not m["paid"] or m["ref"] or (13<=m["buy"]<=43 and m["creditable"]):
        return 0
    return 100

def end(m,reason):
    refund=m["paid"] if reason=="airline" or m["ref"] else 0
    m["returned"]+=refund
    m["cash"]+=refund
    m["status"]=reason

def default(m,h,d):
    k=set(m["heard"])
    signal=(.09*("death" in k)+.12*("meeting" in k)+.30*("global" in k)
            +.17*("emergency" in k)+.38*("advice" in k and d<43)*h["trust"]
            +.10*("abroad" in k)+.40*("local" in k)+.12*("air" in k))
    pressure=signal*(.55+.55*h["worry"]+.24*m["concern"]+.24*h["vulnerable"])
    sticky=.48+.42*h["resolve"]+.18*(m["paid"]>0 and not m["ref"])
    sticky+=.48*(h["purpose"] in ("medical care","funeral","essential work") or m["essential"] or "campus" in k)
    if pressure<sticky:
        return "keep"
    if not m["held"] and pressure<sticky+.40 and fee(m)<=m["cash"]:
        return "later"
    return "drop" if pressure>=sticky+.12 else "keep"

def step(state,params,rng,t):
    p=params
    d=t-1
    z=blank()
    state["daily"]=z
    state["ask"]=[]
    ex=random.Random(p["_seed"]*100003+t)
    listed=1-(1-331238/668259)*clip((d-34)/10) if p["cuts"] else 1
    # Monthly close-in rate is not an early-March daily rate. Ramp from March 11;
    # approximate March monthly incidence by concentrating losses in its last weeks.
    close=(.413 if d>=44 else .169*31/((44-23+1)/2)*clip((d-22)/21)) if p["cuts"] else 0
    capacity=[]
    for base in state["ordinary"][d]:
        a,b=exo_pair(ex)
        capacity.append((base+p["spare"]) if a<listed and b>=close else 0)
    z["seats"]=sum(capacity)
    cast=p["_data"]["travellers"]
    queue=[]
    sched=public(p)
    events=[{"kind":"info","text":bi(NEWS[k][0],NEWS[k][2])} for day,k in sched if day==d]
    for i,(h,m) in enumerate(zip(cast,state["people"])):
        priority=ex.random()
        m["fresh"]=[]
        if not live(m):
            continue
        business=h["purpose"]=="business"
        ban=.13*clip((d-13)/4)+.71*clip((d-17)/15)
        veto=(business and p["bans"] and m["employer"]<ban and not (m["exception"] and m["essential"]))
        if veto or (m["meeting"] and d>=18):
            end(m,"employer" if veto else "event")
            z["forced"]+=1
            continue
        a=m["plan"]
        m["plan"]="keep"
        if a=="drop":
            end(m,"voluntary")
            z["dropped"]+=1
            continue
        if a=="later" and fee(m)<=m["cash"]:
            cost=fee(m)
            m["fees"]+=cost
            m["cash"]-=cost
            shift=21
            m["due"]+=shift
            if m["status"]=="idea":
                m["buy"]=max(d+1,m["buy"]+shift)
            m["held"]=True
            m["lastmove"]=d
            z["moved"]+=1
        if m["status"]=="idea" and m["buy"]<=d:
            cost=price(p,d,m)
            if cost>m["cash"]:
                end(m,"voluntary")
                z["dropped"]+=1
                continue
            m.update(status="ticket",paid=cost,buy=d,cash=m["cash"]-cost,spent=cost)
            z["bookings"]+=1
            if m["heard"]:
                m["fresh"].append("purchase")
        if m["due"]==d:
            z["wanted"]+=1
            queue.append((m["orig"]!=d,priority,i))
            continue
        personal=[(x+m["delay"],k) for x,k in sched]
        personal.append((m["local"],"local"))
        if h["purpose"]=="student":
            personal.append((m["campus"],"campus"))
        for delivery,k in personal:
            if delivery==d and k not in m["heard"]:
                m["heard"].append(k)
                m["fresh"].append(k)
                if k=="campus":
                    m["due"]=min(m["due"],d+6)
                    m["buy"]=min(m["buy"],m["due"]-1) if not m["paid"] else m["buy"]
        review=m["held"] and d-m["last"]>=10 and d-m["lastmove"]>=10
        if m["fresh"] or review:
            if m["asked"]<p["max_asks"]:
                state["ask"].append(i)
                m["last"]=d
                m["asked"]+=1
            elif p["max_asks"]==0:
                m["plan"]=default(m,h,d)
                m["last"]=d
    for _,__,i in sorted(queue):
        m=state["people"][i]
        r=m["route"]
        if capacity[r]>0:
            capacity[r]-=1
            m["status"]="flew"
            z["flew"]+=1
        else:
            end(m,"airline")
            z["forced"]+=1
    return events

def exo_pair(r):
    return r.random(),r.random()

def decisions(state,params,t):
    d=t-1
    p=params
    out=[]
    for i in state["ask"]:
        m=state["people"][i]
        h=p["_data"]["travellers"][i]
        blind=p["blind"]
        when="End of day %d"%d if blind else "Evening of %s, 2020, United States"%date(d)
        news=" ".join(NEWS[k][int(blind)] for k in m["heard"])
        fare=m["paid"] or price(p,d,m)
        purpose="journey home from campus" if "campus" in m["heard"] else h["purpose"]
        desc=("%s. Through %s or direct notices you know: %s Your %s trip leaves in %d days. "
              "%s Your available travel money is $%d. If you drop it you miss the purpose of the visit "
              "and forfeit $%d already paid. Postponing means waiting three weeks and paying $%d to change "
              "(a paid ticket carries over, not a cash refund). Flying means time around strangers; "
              "the risk to you or your contacts is uncertain.")%(
            when,h["channel"],news,purpose,m["due"]-d,
            ("You hold a $%d ticket."%fare if m["paid"] else "No ticket yet; the current quote is $%d."%fare),
            m["cash"],0 if m["ref"] else m["paid"],fee(m))
        if m["held"]:
            desc+=" You have already postponed once."
        if m["essential"]:
            desc+=" Your work trip is classed as essential."
        if d>=43 and "advice" in m["heard"]:
            desc+=" The original advice was for a limited period."
        opts=[{"id":"keep","label":bi("Carry on exactly as before with the current date","今の予定をそのまま続ける")}]
        if fee(m)<=m["cash"]:
            opts.append({"id":"later","label":bi("Move this trip back three weeks","この旅行を3週間延期する")})
        opts.append({"id":"drop","label":bi("Give up this trip","この旅行を取りやめる")})
        out.append(dict(key="person:%d"%i,name=h["name"],agent="traveller",mode="pick",node="plans",
            persona=("%s. Age %d; %s. Personal health concern: %s; vulnerable relative: %s. "
                     "Worry %.2f, trust in advice %.2f, determination %.2f (0–1). %s")%(
                h["work"],m["age"],h["health"],"high" if m["concern"] else "ordinary",
                "yes" if h["vulnerable"] else "no",h["worry"],h["trust"],h["resolve"],h["story"]),
            situation=desc,facts={"days_until_departure":m["due"]-d,"ticket_paid":m["paid"],
            "cash":m["cash"],"change_fee":fee(m)},question="What, if anything, do you change about this trip?",
            options=opts,default={"choice":default(m,h,d)}))
    return out

def apply(state,params,rng,t,action):
    m=state["people"][int(action["key"].split(":")[1])]
    choice=action.get("choice","keep")
    m["plan"]=choice if choice in ("keep","later","drop") else "keep"

def metrics(state,params,t):
    d=max(0,min(69,t-1))
    z=dict(state["daily"])
    z["sim_index"]=100*z["flew"]/max(1,sum(state["ordinary"][d]))
    rows=params["_data"]["reference"]
    z["real_travellers_index"]=float(rows[d]["travellers_index"])
    return z

def view(state,params,t):
    z=state["daily"]
    people=state["people"]
    n=len(people)
    cap=max(1,z["wanted"],z["seats"])
    nodes=[]
    for key,en,ja,x,v,hi in [
        ("plans","Open itineraries","残る旅程",12,sum(live(m) for m in people),n),
        ("gate","Wanted to fly today","本日の搭乗希望",50,z["wanted"],cap),
        ("screen","Through security","保安検査を通過",88,z["flew"],cap)]:
        nodes.append(dict(id=key,label=bi(en,ja),x=x,y=50,value=v,max=hi))
    return dict(clock=bi(date(max(0,t-1)),"第%d日（0日起算）"%max(0,t-1)),nodes=nodes,
                links=[dict(a="plans",b="gate",value=z["wanted"],max=cap),
                       dict(a="gate",b="screen",value=z["flew"],max=cap)])

def invariants(state,params,t):
    z=state["daily"]
    errors=[]
    if z["flew"]>min(z["wanted"],z["seats"]):
        errors.append("Boardings exceed willing travellers or seats")
    for m in state["people"]:
        if m["cash"]<0 or m["cash"]!=m["initial"]-m["spent"]-m["fees"]+m["returned"]:
            errors.append("Ticket cash ledger does not balance")
            break
        if live(m) and m["due"]<t:
            errors.append("Live itinerary past departure")
            break
    return errors