"""Tick t closes day d=t-1, Monday 13 September = 0. Figures describe that
day, including its morning delivery. Evening decisions first affect d+1.
Reference outcomes enter only the observer's metrics; never call metrics
from a rule, request or map. All volumes are litres in the miniature economy.
"""
import math
import random

W = [1.0525]*4 + [1.12,.86,.81]
WD = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
AREAS = ["North estate","Market town","Valley villages","South estate","Rail suburb","Outer ring"]
JA = ["北団地","市場町","谷の集落","南団地","駅前郊外","外環地区"]
def bi(en,ja):
    return {"en":en,"ja":ja}

def date(d):
    return WD[d%7]+" "+(str(13+d)+" Sep" if d<18 else str(d-17)+" Oct")

def cast(p):
    return p["_data"]["drivers"]

def init(params,rng):
    p=params
    c=cast(p)
    cars=[]
    norm=[0.0]*6
    mean=sum(h["mileage"] for h in c)/len(c)
    for h in c:
        petrol=h["fuel"]=="petrol"
        miles=p["miles"]*h["mileage"]/mean
        use=miles*1.609344*(49.7/745 if petrol else 52.6/835)
        size=p["tank"]*h["size"]
        low=max(2*use,size*h["reserve"])
        low=min(.45*size,low)
        lot=min(size-low,use*p["gap"]*math.exp(.55*h["interval_z"]))
        j=int(h["district"])
        norm[j]+=use
        cars.append(dict(f=low+lot*h["phase"],size=size,low=low,lot=lot,use=use,
                         miles=miles,j=j,price=1.352 if petrol else 1.369,
                         mode="usual",until=-1,known=[],note=[],asked=0,last=-99,
                         wait=0,blocked=False,queue=False))
    cap=[max(.01,n)*p["capacity"] for n in norm]
    stock=[x*p["opening"]/100 for x in cap]
    return dict(cars=cars,norm=norm,cap=cap,s=stock,news=False,coverage=False,
                initial_car=sum(x["f"] for x in cars),initial_site=sum(stock),
                burned=0,supplied=0,transferred=0,ask=[],sold=0,wanted=0,failed=0,
                short=0,purchases=0,loads=[0]*6)

def delivery(s,p,t,ex):
    d=t-1
    rows=p["_data"]["reference"]
    idx=float(rows[d]["deliveries_index"])
    if p["early"] and 12<=d<30:
        # Pair the exact volumes; don't subtract more than a donor day contains.
        donor=d+9 if d<21 else d
        shift=min(p["slice"],float(rows[donor]["deliveries_index"]))
        idx+=shift if d<21 else -shift
    total=sum(s["norm"])*idx/100
    room=[max(0,k-v) for k,v in zip(s["cap"],s["s"])]
    route=[n*ex.uniform(.65,1.35) for n in s["norm"]]
    priority=[r*(r/k)**3 for k,r in zip(s["cap"],room)]
    mix=.45 if d>=13 else 0
    weights=[(1-mix)*a/sum(route)+mix*b/max(.00001,sum(priority)) for a,b in zip(route,priority)]
    loads=[0.0]*6
    left=total
    for _ in range(7):
        active=[j for j in range(6) if room[j]-loads[j]>1e-8]
        denom=sum(weights[j] for j in active)
        if left<1e-8 or not denom: break
        for j in active:
            loads[j]+=min(room[j]-loads[j],left*weights[j]/denom)
        left=max(0,total-sum(loads))
    s["loads"]=loads
    s["supplied"]+=sum(loads)
    for j,v in enumerate(loads): s["s"][j]+=v

def policy(x,h):
    # Threshold L, purchase target increment L, reachable sites, driving fraction.
    m=x["mode"]
    if m=="buffer":
        return max(x["low"],.5*x["size"]),max(x["lot"],.62*x["size"]),2,1
    if m=="search":
        return x["low"],x["lot"],3,1
    if m=="save":
        return x["low"],x["lot"],1,h["essential"]
    return x["low"],x["lot"],1,1

def hear(x,key):
    if key not in x["known"]:
        x["known"].append(key)
        x["note"].append(key)

TEXT={
 "report":"A fuel company says some sites will close because tanker drivers are scarce.",
 "tv":"You have seen queue pictures on TV.",
 "social":"You have seen queue pictures shared online.",
 "press":"You have seen a newspaper photograph of a forecourt queue.",
 "minister":"Ministers say there is enough fuel nationally and ask people to buy as usual.",
 "sharing":"Suppliers can now share delivery arrangements.",
 "standby":"Military tanker drivers are on standby, not yet delivering.",
 "army":"Military tanker drivers have begun deliveries.",
 "busy":"On your trip you encountered a queue.",
 "clear":"On a subsequent visit the queue was short again.",
 "empty":"You tried to refuel but obtained nothing.",
 "again":"On a later trip you could buy fuel again.",
 "stranded":"Your tank ran out before you completed your planned driving.",
 "limit":"A purchase ceiling is in force.",
 "lift":"The purchase ceiling has ended.",
 "review":"Time to review your temporary travel plan."
}

def step(state,params,rng,t):
    s,p=state,params
    d=t-1
    ex=random.Random(p["_seed"]*100003+t)
    delivery(s,p,t,ex)
    for k in ["sold","wanted","failed","short","purchases"]: s[k]=0
    order=list(range(len(cast(p))))
    ex.shuffle(order)
    visits=[0]*6
    usual=[0.0]*6
    for x in s["cars"]: usual[x["j"]]+=W[d%7]*x["use"]/x["lot"]
    cap=p["limit"] if 11<=d<21 else 0
    for i in order:
        h,x=cast(p)[i],s["cars"][i]
        x["note"]=[]
        if d>x["until"]: x["mode"]="usual"
        low,lot,tries,fraction=policy(x,h)
        burn=x["use"]*W[d%7]*fraction
        used=min(x["f"],burn)
        if used+1e-8<burn:
            s["short"]+=1
            hear(x,"stranded")
        x["f"]-=used
        s["burned"]+=used
        if x["f"]>low: continue
        want=min(x["size"]-x["f"],lot)
        s["wanted"]+=want
        ceiling=min(want,cap/x["price"]) if cap else want
        if cap: hear(x,"limit")
        got=0
        for k in range(tries):
            j=(x["j"]+k)%6
            visits[j]+=1
            # Burst above ordinary daily arrivals, expressed as equivalent wait.
            x["wait"]=round(4*max(0,visits[j]-usual[j]))
            if x["wait"]>=12 and not x["queue"]:
                x["queue"]=True
                x["note"].append("busy")
            elif x["wait"]<=4 and x["queue"]:
                x["queue"]=False
                x["note"].append("clear")
            free=max(0,s["s"][j]-s["cap"][j]*p["heel"]/100)
            got=min(ceiling,free)
            if got>1e-8:
                s["s"][j]-=got
                x["f"]+=got
                s["sold"]+=got
                s["purchases"]+=1
                if x["blocked"]:
                    x["note"].append("again")
                    x["blocked"]=False
                break
        else:
            s["failed"]+=1
            if not x["blocked"]:
                x["note"].append("empty")
            x["blocked"]=True
    s["transferred"]+=s["sold"]
    if d==10 and p["story"]: s["news"]=True
    if d>=11 and (s["news"] or sum(visits)>1.5*sum(usual)):
        s["coverage"]=True
    army=12 if p["early"] else 21
    events=[]
    if d==10 and s["news"]:
        events.append({"kind":"alert","text":bi("Evening bulletin: some forecourts face closure.","夕方の報道：一部給油所が休業へ。")})
    if d==13:
        events.append({"kind":"info","text":bi("Companies may pool deliveries.","事業者間の共同配送が可能になる。")})
    if d==army:
        events.append({"kind":"milestone","text":bi("Military drivers start deliveries.","軍の運転手が配送を開始。")})
    s["ask"]=[]
    for i,(h,x) in enumerate(zip(cast(p),s["cars"])):
        r=[ex.random() for _ in range(8)]
        tv=h["tv"]=="yes"
        social=h["social"]=="yes"
        reach=.72 if tv or social else .22
        if s["news"] and d<=14 and r[0]<reach: hear(x,"report")
        if s["coverage"]:
            if 11<=d<=16:
                if tv and p["pictures"] and r[1]<.58: hear(x,"tv")
                if social and r[2]<.48: hear(x,"social")
                if h["paper"]=="yes" and r[3]<.46: hear(x,"press")
            if 11<=d<=17 and r[4]<reach: hear(x,"minister")
            if 13<=d<=15 and r[5]<reach*.6: hear(x,"sharing")
            if 14<=d<army and r[6]<reach*.5: hear(x,"standby")
            if army<=d<=army+3 and r[7]<reach: hear(x,"army")
        if "limit" in x["known"] and not cap: hear(x,"lift")
        if x["mode"]!="usual" and d-x["last"]>=5: x["note"].append("review")
        if x["note"] and x["asked"]<p["asks"] and d<41: s["ask"].append(i)
    return events

OPTIONS=[
 ("keep","Carry on exactly as before","今の計画のまま"),
 ("usual","Use my ordinary refill and driving routine","普段の運転・給油に戻す"),
 ("buffer","Refuel below half a tank; seek a larger purchase, up to two sites","半分を切れば多めに給油、2店まで"),
 ("search","Keep my usual trigger, but try up to three sites","給油時期は変えず3店まで探す"),
 ("save","Drop optional mileage, keep ordinary refill habits","不要な移動を控え、給油は通常どおり")
]

def fallback(x,h):
    keys=x["known"]
    risk=h["worry"]+.20*h["essential"]+.18*h["follow"]*any(k in keys for k in ("tv","social","press"))
    risk+=.32*x["blocked"]+.12*x["queue"]-.28*h["trust"]*("minister" in keys)
    if x["mode"]!="usual" and (set(x["note"]) & {"again","clear","army","review"}):
        return "usual" if not x["blocked"] else "search"
    if risk>.91 and (x["blocked"] or x["queue"] or set(keys)&{"report","social","press","tv"}):
        return "save" if h["essential"]<.5 and x["f"]<x["low"] else "buffer"
    return "search" if x["blocked"] else "keep"

def decisions(state,params,t):
    s,p=state,params
    d=t-1
    out=[]
    for i in s["ask"]:
        h,x=cast(p)[i],s["cars"][i]
        lo,lot,n,frac=policy(x,h)
        time=("Day %d (%s)"%(d,WD[d%7]) if p["blind"] else date(d)+" 2021, Great Britain")
        situation=("%s, evening. Your %s car has %.1f of %.1f L; normal driving is %.1f miles/day. "
                   "Ordinarily you seek %.1f L below %.1f L. Current plan: below %.1f L seek up to %.1f L, "
                   "try %d site(s), drive %.0f%% of normal. Missing a journey could interfere with your %s duties. "
                   "A separate trip takes about %d minutes return before waiting; your last estimated wait was %d minutes. "
                   "An extra 10 L ties up %.2f in cash. "%
                   (time,h["fuel"],x["f"],x["size"],x["miles"],x["lot"],x["low"],lo,lot,n,100*frac,
                    h["job"],2*h["minutes"],x["wait"],10*x["price"]))
        if x["known"]: situation+="What has reached you so far: "+" ".join(TEXT[k] for k in x["known"])+" "
        situation+="This evening's reason to reconsider: "+" ".join(TEXT[k] for k in x["note"])
        if "limit" in x["known"] and 11<=d<21 and p["limit"]:
            situation+=" Ceiling: %d per purchase."%p["limit"]
        situation+=" A changed temporary plan lasts up to seven driving days unless revised."
        out.append({"key":"driver:%d"%i,"name":h["name"],"agent":"driver","mode":"pick","node":"s%d"%x["j"],
                    "persona":"%s; %s. Worry %.2f, follows others %.2f, official trust %.2f (0–1). %s"%
                    (h["job"],AREAS[x["j"]],h["worry"],h["follow"],h["trust"],h["story"]),
                    "situation":situation,"facts":{"litres":round(x["f"],1),"essential_driving_pct":round(100*h["essential"])},
                    "question":"For tomorrow, what, if anything, do you change?",
                    "options":[{"id":k,"label":bi(a,b)} for k,a,b in OPTIONS],
                    "default":{"choice":fallback(x,h)}})
        x["asked"]+=1
        x["last"]=d
    return out

def apply(state,params,rng,t,action):
    x=state["cars"][int(action["key"].split(":")[1])]
    m=action["choice"]
    if m in ("usual","save","buffer","search"):
        x["mode"]=m
        x["until"]=t+6

def metrics(state,params,t):
    s=state
    d=max(0,t-1)
    denom=sum(s["norm"])*W[d%7]/100
    # Observer-only traces, matched to the completed tick for replay after run.
    row=params["_data"]["reference"][d]
    return {"sales":s["sold"]/denom,"wanted":s["wanted"]/denom,
            "real_sales":float(row["sales_index"]),"real_stock":float(row["stock_pct"]),
            "stock":100*sum(v/k for v,k in zip(s["s"],s["cap"]))/6,
            "dry":100*sum(v<=k*params["heel"]/100+1e-7 for v,k in zip(s["s"],s["cap"]))/6,
            "tank_fill":100*sum(x["f"]/x["size"] for x in s["cars"])/len(s["cars"]),
            "failed":s["failed"],"short":s["short"],"lot":s["sold"]/max(1,s["purchases"])}

def view(state,params,t):
    s=state
    nodes=[{"id":"depot","label":bi("Daily dispatch","本日の配送"),"x":10,"y":50,
            "value":sum(s["loads"]),"max":max(sum(s["norm"])*1.5,sum(s["loads"]))}]
    links=[]
    for j,(v,k) in enumerate(zip(s["s"],s["cap"])):
        key="s%d"%j
        nodes.append({"id":key,"label":bi(AREAS[j],JA[j]),"x":42+36*(j%2),"y":18+32*(j//2),
                      "value":v,"max":k,"sub":bi("%.0f L at close"%v,"終了時 %.0f L"%v),
                      "status":"crit" if v/k<=params["heel"]/100+1e-8 else "warn" if v/k<.16 else "ok"})
        links.append({"a":"depot","b":key,"value":s["loads"][j],"max":max(1,s["loads"][j],1.5*s["norm"][j])})
    return {"clock":date(max(0,t-1))+" / day %d"%max(0,t-1),"nodes":nodes,"links":links}

def invariants(state,params,t):
    s=state
    bad=[]
    if any(not -1e-7<=x["f"]<=x["size"]+1e-7 for x in s["cars"]): bad.append("Car tank out of bounds")
    if any(not -1e-7<=v<=k+1e-7 for v,k in zip(s["s"],s["cap"])): bad.append("Site tank out of bounds")
    if abs(sum(s["s"])-s["initial_site"]-s["supplied"]+s["transferred"])>1e-5: bad.append("Site ledger imbalance")
    if abs(sum(x["f"] for x in s["cars"])-s["initial_car"]+s["burned"]-s["transferred"])>1e-5: bad.append("Car ledger imbalance")
    if s["sold"]>s["wanted"]+1e-7: bad.append("Sold more than sought")
    return bad