"""One tick closes three months: pay, care and the 60 workdays are already history
when anyone is asked. A reply is an intention for a later household conversation,
shift, or staffing meeting. The path parameter is read only at initialization.
All coefficients not given by the observer are assumptions; no outcome data.
"""
import random

def bi(en, ja):
    return {"en": en, "ja": ja}

def clip(x, lo=0, hi=100):
    return min(hi, max(lo, x))

# Slot assignment is deterministic, so a random draw cannot omit a parent or manager.
ROLES = ["wife", "child", "boss", "host", "founder"] + ["old peer"]*3 + ["host peer"]*2 + ["lead peer"]*3
TIES = {
    "wife":"Your partner shares the mortgage and the evenings. You want dependable income and employment.",
    "child":"This is your parent. You want time to play and a dependable bedtime routine.",
    "boss":"Your direct report knows the old services. You want reliable handovers and room to develop people.",
    "host":"This engineer could join your team. You need someone you can entrust with the migration.",
    "founder":"An old friend could lead engineering at your firm. You need delivery without damaging the friendship.",
    "old peer":"You share the legacy pager. You want fair rotations and usable documentation.",
    "host peer":"You work in the receiving team. You want someone who tests ideas and reviews your designs.",
    "lead peer":"You work in the founder's small team. You need a lead who shares decisions and responds to incidents."
}
SITE = {"old peer":"current","host peer":"internal","lead peer":"startup","boss":"current","host":"internal","founder":"startup"}
PLACE = {"current":"元部署","internal":"異動先","startup":"新会社","search":"求職中"}
SIGNALS = ["care","seat","reorg","funding","lost_client","return_offer","expenses","other_income"]
SPEECH = {
 "wife":[("Let's try this budget together.","この予算で一緒にやってみよう。"),("I need a safer income plan before we take on more.","これ以上引き受ける前に、収入が途切れたときのことを決めたい。")],
 "child":[("Come play with me!","いっしょに遊ぼう！"),("Stay here a little longer.","もうちょっとここにいて。")],
 "boss":[("I'll release you for the move and protect some design time until then.","異動なら送り出すよ。それまでも設計の時間は取ろう。"),("I need you on maintenance until we have cover.","引き継げるまでは保守をお願いしたい。")],
 "host":[("I'll sponsor the move and give you a design to own.","受け入れを推すよ。設計も一つ任せたい。"),("I can't sponsor the move now; let's narrow the scope.","今は受け入れを推せない。担当範囲も絞りたい。")],
 "founder":[("You decide the architecture; I'll cover the client call.","設計は任せる。顧客との打ち合わせは僕が出るよ。"),("Let's keep the decisions with me for now.","今は僕の方で決めさせてほしい。")],
 "peer":[("I'll share the pager so you can try the design.","設計を試せるよう、当番を分けよう。"),("I need you to take your own tickets for now.","今は自分の担当分を引き受けてほしい。")]
}
KEEP = ("keep","Carry on exactly as before","今までどおりにする")
PATH = [("current","Ask for the original role","元部署の仕事を希望する"),
        ("internal","Apply for the receiving team","異動先を希望する"),
        ("startup","Take up the friend's offer","友人の誘いに応じる"),
        ("protect","Protect evenings; decline optional overtime","任意の残業を断り、夜を空ける"),
        ("study","Ask for a protected technical trial","技術検証の時間を求める"),
        ("usual","Resume ordinary hours and assignments","通常の勤務・担当に戻す")]

def init(p,rng):
    goal={"join_startup":"startup","seek_internal_transfer":"internal","stay_current_role":"current"}[p["path"]]
    people=[]
    for i,h in enumerate(p["_data"]["circle"]):
        people.append({"role":ROLES[i],"regard":h["warmth"],"stance":0,"next_stance":0,
                       "asked":0,"last":-10,"observation":"","line":"","occasion":h["rhythm"]})
    target=3*(600000*p["net_share"]+p["other_income"]-130000-p["expenses"]-35000)
    return {"circle":people,"work":"startup" if goal=="startup" else "current","goal":goal,
            "pace":"usual","intention":"keep","cash":p["cash_start"],"expected":target,
            "income_total":0,"spent_total":0,"options":0,"grant_left":160,"grant_started":goal=="startup",
            "crisis":0,"fatigue":25,"burden":0,"missed":0,"satisfaction":55,"job":50,"saved":0,
            "learning":0,"wanted_days":0,"maintenance":0,"family_hours":0,"work_hours":0,
            "signals":{k:p[k] for k in SIGNALS},"news":[],"ask":[],"you_asks":0,"ask_you":False,
            "last_meeting":"","feedback":[],"records":[],"care_hours":0}

def step(s,p,rng,t):
    old=s["work"]
    oldgoal=s["goal"]
    people=s["circle"]
    changes=[k for k in SIGNALS if s["signals"][k]!=p[k]]
    news=["%s now %s (was %s)"%(k,p[k],s["signals"][k]) for k in changes]
    s["signals"]={k:p[k] for k in SIGNALS}
    news+=s["feedback"]
    s["feedback"]=[]
    for i,a in enumerate(people):
        if (t+i)%a["occasion"]==0:
            a["stance"]=a["next_stance"]
    command=s["intention"]
    if command in PLACE:
        s["goal"]=command
    elif command in ("usual","protect","study"):
        s["pace"]=command
    s["intention"]="keep"
    goal=s["goal"]
    s["crisis"]=s["crisis"]+1 if p["lost_client"] and not p["funding"] else 0
    result=""
    if goal!=old:
        if goal=="startup":
            if not p["lost_client"]:
                s["work"]="startup"
            else:
                result="Startup hiring is suspended."
        elif goal=="current":
            if old=="internal" or p["return_offer"] or (t%2==0 and people[2]["stance"]>=0):
                s["work"]="current"
            elif t%2==0:
                result="Former manager cannot take you back yet."
        elif goal=="internal" and t%2==0:
            if p["seat"] and people[3]["stance"]>=0 and (old!="current" or people[2]["stance"]>=0):
                s["work"]="internal"
            else:
                result="Transfer held: seat=%s, releasing stance=%s, receiving stance=%s."%(p["seat"],people[2]["stance"],people[3]["stance"])
    if s["work"]=="startup" and s["crisis"]>=2:
        s["work"]="search"
        s["goal"]="search"
        result="Lead position eliminated. No salary until a new placement."
    work=s["work"]
    if old=="startup" and work!=old:
        s["grant_left"]=0
    if work=="startup":
        s["grant_started"]=True
        vest=min(10,s["grant_left"])
        s["options"]+=vest
        s["grant_left"]-=vest
    if result and result!=s["last_meeting"]:
        news.append(result)
    if result or work!=old:
        s["last_meeting"]=result
    if work!=old:
        news.append("Work changed from %s to %s."%(old,work))
    if t==1:
        news.append("First quarter in the opening plan: %s; requested destination: %s."%(work,goal))
    if t==17:
        news.append("School routines now replace the early-childhood care budget.")
    # Same underlying tickets and opportunities in every branch; choices alter capacity.
    exo=random.Random(p["_seed"]*100003+t)
    peers=[a for a in people if "peer" in a["role"] and SITE[a["role"]]==work]
    cover=sum(a["stance"] for a in peers)/max(1,len(peers))
    manager=people[{"current":2,"internal":3,"startup":4,"search":2}[work]]["stance"]
    integration=p["reorg"] and work in ("current","internal")
    rescue=p["funding"] and work=="startup"
    crunch=p["lost_client"] and work=="startup"
    maintenance=hours=learn=wanted=0
    for day in range(60):
        ticket,incident,opportunity=exo.random(),exo.random(),exo.random()
        overtime=clip({"current":0.35,"internal":0.55,"startup":1.35,"search":0}[work]+integration*.65+crunch*1.1-rescue*.9-cover*.4+(incident<.18)*1.3,0,4)
        if s["pace"]=="protect":
            overtime=min(.35,overtime)
        shift=8+overtime if work!="search" else 3
        legacy=clip({"current":5.9,"internal":3.1,"startup":2.7,"search":0}[work]+(ticket-.5)*3+integration*1.4+crunch*2-manager*.8-cover*.5,0,shift)
        if work=="search":
            legacy=0
        trial=opportunity<clip(.60+.25*(s["pace"]=="study")-.08*(s["pace"]=="protect"),0,1)
        delivery={"current":1.8,"internal":3.7,"startup":5.1,"search":2.2}[work]
        available=shift-legacy-delivery+(.9 if s["pace"]=="study" else 0)
        wanted+=int(trial)
        learn+=int(trial and available>=1)
        hours+=shift
        maintenance+=legacy
    care=max(12,(92 if t<=16 else 60)+30*p["care"])
    family=clip(300-max(0,hours-480)-care+10*people[0]["stance"]+4*people[1]["stance"],0,320)
    fatigue=clip(.55*s["fatigue"]+.45*clip(18+.52*max(0,hours-480)+.22*care+10*crunch))
    gross={"current":7200000,"internal":7200000,"startup":6200000,"search":0}[work]
    net=round(gross/4*p["net_share"]+3*p["other_income"])
    childcare=(35000 if t<=16 else 45000)+12000*p["care"]
    # With household backing, economies are possible but bounded; never assume salary parity.
    thrift=15000 if people[0]["stance"]>0 and work in ("startup","search") else 0
    spent=round(3*(130000+p["expenses"]+childcare-thrift)+max(0,hours-510)*180)
    saved=net-spent
    s["cash"]+=saved
    s["income_total"]+=net
    s["spent_total"]+=spent
    strain=clip((215-family)*.65+max(0,s["expected"]-saved)/6500+max(0,-s["cash"])/50000)
    missed=clip((32-learn)*2.8)
    job=clip(42+learn*1.05+manager*5+cover*4-fatigue*.27-18*(work=="search"))
    s.update(learning=learn,wanted_days=wanted,maintenance=maintenance,work_hours=hours,
             care_hours=care,family_hours=family,fatigue=fatigue,job=job,saved=saved,
             salary_gross=gross,quarter_income=net,quarter_expenses=spent,child_age=2+t/4,
             burden=s["burden"]+(strain-s["burden"])/t,missed=s["missed"]+(missed-s["missed"])/t)
    # Only contacts in a position to witness the change update their impression.
    ask=[]
    for i,(a,h) in enumerate(zip(people,p["_data"]["circle"])):
        role=a["role"]
        home=i<2
        application=i in (2,3) and goal=="internal"
        touch=home or application or SITE.get(role) in (work,old) or (i==4 and goal=="startup") or (i==2 and goal=="current")
        if not touch:
            continue
        if home:
            signal=clip((family/260 if i==1 else .95-strain/160-.09*(work=="startup")) ,0,1)
            obs=("This quarter there were %.0f unhurried hours together."%family if i==1 else
                 "Our child is %.2f. We saved Y%d versus Y%d planned, with Y%d net cash. There were %.0f unhurried hours together; work is %s."%(s["child_age"],saved,s["expected"],s["cash"],family,work))
        else:
            firsthand=SITE.get(role)==work
            signal=clip(.63+.004*learn-.003*fatigue+.08*cover if firsthand else a["regard"],0,1)
            obs=("On our team I saw %d learning days and %.0f maintenance hours; work hours total %.0f."%(learn,maintenance,hours) if firsthand else
                 "I heard about the engineer's current team (%s) and placement request (%s)."%(work,goal))
            if application:
                obs+=" The transfer seat is %s."%("budgeted" if p["seat"] else "frozen")
        a["regard"]=clip(.82*a["regard"]+.18*signal,0,1)
        a["observation"]=obs
        relevant_changes=(set(changes)&(set(["care","other_income","expenses","lost_client"]) if home else
                          set(["funding","lost_client"]) if SITE.get(role)=="startup" else set(["seat","reorg","return_offer"])))
        trigger=t==1 or old!=work or oldgoal!=goal or relevant_changes or (application and result and t%2==0)
        if a["asked"]<p["max_asks"] and (trigger or (t-a["last"]>=4+a["occasion"] and abs(signal-.65)>.12)):
            ask.append(i)
    s["satisfaction"]=clip(.50*job+.23*clip(family/2.5)+.17*(100-strain)+.10*people[0]["regard"]*100)
    s.update(news=news,ask=ask,ask_you=s["you_asks"]<p["you_cap"] and bool(news or t==2 or t%4==0))
    ev=[]
    if old!=work or (result and news):
        ev.append({"kind":"info","text":bi("Placement: %s. %s"%(work,result),"配置：%s。%s"%(PLACE[work],"希望は保留中。" if result and work!="search" else ""))})
    if t==2 or t%4==0:
        m=metrics(s,p,t)
        s["records"].append(dict(m,quarter=t,work=work,cash=s["cash"]))
        ev.append({"kind":"milestone","text":bi(
            "Age %.1f: %s. Saved ¥%d this quarter (plan ¥%d); regret about home %.0f, missed challenge %.0f."%(32+t/4,work,saved,s["expected"],s["burden"],s["missed"]),
            "%.1f歳、%s。当期貯蓄%d円（見込み%d円）。家庭への負担の後悔%.0f、挑戦を逃した後悔%.0f。"%(32+t/4,PLACE[work],saved,s["expected"],s["burden"],s["missed"]))})
    return ev

def request(key,name,persona,situation,facts,options,default):
    return {"key":key,"agent":"person","mode":"pick","name":name,"persona":persona,
            "situation":situation,"facts":facts,"question":"What, if anything, do you change at your next occasion to act?",
            "options":[{"id":k,"label":bi(e,j)} for k,e,j in options],"default":{"choice":default}}

def decisions(s,p,t):
    req=[]
    if s["ask_you"]:
        h=p["_data"]["protagonist"]
        options=[KEEP]+[o for o in PATH if o[0]!=s["pace"] and o[0]!=s["goal"] and not(o[0]=="startup" and p["lost_client"])]
        d="keep"
        if s["work"]=="search" and s["goal"]=="search":
            d="current"
        elif s["fatigue"]>68 and s["pace"]!="protect":
            d="protect"
        elif s["learning"]<12 and s["pace"]=="usual":
            d="study"
        elif s["learning"]<15 and s["pace"]=="study" and s["goal"]=="current" and p["seat"]:
            d="internal"
        snapshot=("Quarter %d, age %.2f, child %.2f. Work %s, goal %s, routine %s. Tried for %d learning days, got %d; "
                  "%.0f maintenance hours, %.0f family hours, fatigue %.0f/100. Gross salary Y%d/year. This quarter income Y%d, "
                  "expenses Y%d including Y390000 mortgage; saved Y%d, expected Y%d; net cash Y%d. %d vested options cannot be spent. "
                  "A move may cost salary and evenings; waiting may cost design experience. Transfer requires a seat and both managers' assent. "
                  "Home-burden regret %.0f, missed-challenge regret %.0f.")%(
                  t,32+t/4,s["child_age"],s["work"],s["goal"],s["pace"],s["wanted_days"],s["learning"],s["maintenance"],
                  s["family_hours"],s["fatigue"],s["salary_gross"],s["quarter_income"],s["quarter_expenses"],s["saved"],
                  s["expected"],s["cash"],s["options"],s["burden"],s["missed"])
        lines=[a["role"]+": "+a["line"] for a in s["circle"] if a["line"]]
        req.append(request("you",h["name"],h["profile"]+"\n\n"+snapshot,snapshot+" Latest news: "+"; ".join(s["news"] or ["scheduled reflection"])+". Last conversations: "+"; ".join(lines),metrics(s,p,t),options,d))
        s["you_asks"]+=1
    for i in s["ask"]:
        a=s["circle"][i]
        h=p["_data"]["circle"][i]
        r=a["role"]
        positive,negative=SPEECH.get(r,SPEECH["peer"])
        opt=[KEEP,("back",*positive),("limit",*negative)]
        default="keep"
        if a["regard"]>.69+h["caution"]*.10 and a["stance"]!=1:
            default="back"
        if a["regard"]<.32+h["caution"]*.15 and a["stance"]!=-1:
            default="limit"
        cost=("Trying a leaner budget saves money but costs comforts; refusing uncertainty may close an opportunity." if i==0 else
              "Playing together means stopping what you're doing; you also miss your parent when they're busy." if i==1 else
              "Offering cover or design time takes capacity from your own commitments; holding back can delay the engineer's growth.")
        situation="End of quarter %d. %s %s Your current stance is %d (−1 limit, 0 ordinary, 1 back)."%(t,a["observation"],cost,a["stance"])
        if i==1:
            situation="You are %.2f years old. %s %s"%(s["child_age"],a["observation"],cost)
        req.append(request("circle:%d"%i,h["name"],r+". "+TIES[r]+" "+h["story"]+" Personal inclination: "+h["inclination"],situation,
                           {"regard":round(a["regard"],2),"stance":a["stance"]},opt,default))
        a["asked"]+=1
        a["last"]=t
    return req

def apply(s,p,rng,t,action):
    k=action["key"]
    c=action.get("choice","keep")
    if k=="you":
        s["intention"]=c
        return
    i=int(k.split(":")[1])
    a=s["circle"][i]
    lines=SPEECH.get(a["role"],SPEECH["peer"])
    if c in ("back","limit"):
        v=1 if c=="back" else -1
        if a["next_stance"]!=v:
            s["feedback"].append(a["role"]+": "+lines[v<0][0])
        a["next_stance"]=v
        a["regard"]=clip(a["regard"]+.045*v,0,1)
        en,ja=lines[v<0]
    else:
        en,ja=(("Let's play like usual.","いつもみたいに遊ぼう。") if i==1 else ("I'll carry on as before.","今までどおりにするね。"))
    a["line"]=en
    name=p["_data"]["circle"][i]["name"]
    return [{"kind":"info","text":bi(name["en"]+': “'+en+'”',name["ja"]+"「"+ja+"」")}]

def metrics(s,p,t):
    m={k:round(s[k],2) for k in ("satisfaction","job","fatigue","burden","missed","learning","maintenance","family_hours","saved","expected","options")}
    m.update(regret=round((s["burden"]+s["missed"])/2,2),regard=round(100*sum(a["regard"] for a in s["circle"])/len(s["circle"]),2),wife=round(100*s["circle"][0]["regard"],2))
    return m

def view(s,p,t):
    def node(k,e,j,x,y,val,mx,sub):
        return {"id":k,"label":bi(e,j),"x":x,"y":y,"value":val,"max":mx,"sub":sub}
    nodes=[node("home","Kitchen table","食卓",16,55,s["family_hours"],320,bi("Net cash ¥%d"%s["cash"],"純現金 %d円"%s["cash"])),
           node("you","Engineer","本人",48,51,s["satisfaction"],100,bi(s["work"],PLACE[s["work"]]))]
    links=[{"a":"you","b":"home","value":s["family_hours"],"max":320}]
    for site,y in (("current",15),("internal",50),("startup",85)):
        active=s["work"]==site
        nodes.append(node(site,site.capitalize(),PLACE[site],82,y,s["learning"] if active else 0,60,
                          bi("Working here" if active else "Not working here","在籍中" if active else "在籍していない")))
        links.append({"a":"you","b":site,"value":int(active),"max":1})
    return {"clock":bi("Age %d years %d months"%(32+t//4,t%4*3),"%d歳%dか月"%(32+t//4,t%4*3)),"nodes":nodes,"links":links}

def invariants(s,p,t):
    bad=[]
    if abs(s["cash"]-p["cash_start"]-s["income_total"]+s["spent_total"])>.01:
        bad.append("Household ledger does not balance")
    if not 0<=s["learning"]<=s["wanted_days"]<=60 or not 0<=s["maintenance"]<=s["work_hours"]+.001:
        bad.append("Day or shift capacity exceeded")
    if not 0<=s["options"]<=160-s["grant_left"]<=160:
        bad.append("Grant capacity exceeded")
    if any(not 0<=a["regard"]<=1 or a["asked"]>p["max_asks"] for a in s["circle"]):
        bad.append("Relationship state out of bounds")
    return bad