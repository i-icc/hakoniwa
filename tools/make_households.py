"""Builds the cast for the toilet-paper world: 240 households, each with its own
circumstances, information habits, character and a short life story.

Attributes are drawn by code from stated distributions (assumptions, not survey
data). The life stories are written once by the residents' model and saved, so
every run uses the same people.

    PYTHONPATH=. python tools/make_households.py        # needs OPENAI_API_KEY in .env
"""
import asyncio
import json
import random
from pathlib import Path

from hakoniwa.application.ports import chat_json
from hakoniwa.infrastructure.config import load_settings
from hakoniwa.infrastructure.openai_llm import make_llm

OUT = Path(__file__).resolve().parent.parent / "hakoniwa" / "worlds" / "tp_2020" / "data.json"
N = 240
SURNAMES = [("Sato", "佐藤"), ("Suzuki", "鈴木"), ("Takahashi", "高橋"), ("Tanaka", "田中"), ("Ito", "伊藤"), ("Watanabe", "渡辺"),
            ("Yamamoto", "山本"), ("Nakamura", "中村"), ("Kobayashi", "小林"), ("Kato", "加藤"), ("Yoshida", "吉田"), ("Yamada", "山田"),
            ("Sasaki", "佐々木"), ("Yamaguchi", "山口"), ("Matsumoto", "松本"), ("Inoue", "井上"), ("Kimura", "木村"), ("Hayashi", "林"),
            ("Shimizu", "清水"), ("Mori", "森"), ("Abe", "阿部"), ("Ikeda", "池田"), ("Hashimoto", "橋本"), ("Ishikawa", "石川")]
GIVEN = [("Keiko", "恵子"), ("Hiroshi", "浩"), ("Yumi", "由美"), ("Takashi", "隆"), ("Akiko", "明子"), ("Kenji", "健二"), ("Naoko", "直子"),
         ("Daisuke", "大輔"), ("Mika", "美香"), ("Shota", "翔太"), ("Sachiko", "幸子"), ("Makoto", "誠"), ("Ayumi", "あゆみ"), ("Ryo", "亮"),
         ("Tomoko", "智子"), ("Yuta", "雄太"), ("Kazuko", "和子"), ("Haruto", "陽斗"), ("Misaki", "美咲"), ("Osamu", "修")]
# (label, share, members, typical age band of the person who shops)
KINDS = [("lives alone, in their 20s-30s", 0.16, 1, "20s-30s"), ("lives alone, 40s-50s", 0.08, 1, "40s-50s"),
         ("lives alone, 70 or older", 0.12, 1, "70+"), ("couple without children", 0.20, 2, "30s-60s"),
         ("retired couple", 0.12, 2, "65+"), ("couple with one small child", 0.10, 3, "30s"),
         ("family with two school-age children", 0.14, 4, "40s"), ("three generations under one roof", 0.08, 5, "50s")]
WORK = ["office worker with a long commute", "works shifts at a hospital", "part-time job at a supermarket", "freelance, works from home",
        "runs a small shop", "stays home with the children", "retired", "university student", "factory worker on rotating shifts",
        "care worker", "sales rep who drives all day", "public servant at the town hall"]
INFO = [("sns", 0.30, "checks Twitter many times a day"), ("tv", 0.34, "gets news mostly from morning and evening TV"),
        ("chat", 0.22, "hears things from family and friends on LINE"), ("low", 0.14, "pays little attention to news")]
AREA = [("city centre, small flat, little storage", 0.35), ("suburb, shops within a short drive", 0.45), ("small town, one supermarket and one drugstore", 0.20)]


def pick(rng, table, weight_index=1):
    r, acc = rng.random(), 0.0
    for row in table:
        acc += row[weight_index]
        if r < acc:
            return row
    return table[-1]


def draw(rng, i):
    kind = pick(rng, KINDS)
    info = pick(rng, INFO)
    area = pick(rng, AREA)
    s, g = rng.choice(SURNAMES), rng.choice(GIVEN)
    clamp = lambda v: round(max(0.05, min(0.95, v)), 2)
    older = "70" in kind[3] or "65" in kind[3]
    return {
        "id": i, "name": {"en": f"{g[0]} {s[0]}", "ja": f"{s[1]} {g[1]}"}, "kind": kind[0], "members": kind[2], "age": kind[3],
        "work": "retired" if older else rng.choice(WORK), "area": area[0], "info": info[0], "info_text": info[2],
        "anxiety": clamp(rng.gauss(0.5, 0.2) + (0.08 if kind[2] >= 3 else 0)),       # how easily they worry
        "conformity": clamp(rng.gauss(0.5, 0.2)),                                      # how much they follow what others do
        "trust": clamp(rng.gauss(0.55, 0.2) + (0.08 if older else 0)),                 # trust in official statements
        "shop_gap": rng.choice([1, 2, 2, 3, 3, 4, 5, 7]),                              # days between ordinary shopping trips
        "start_stock": rng.randint(2, 16),                                             # rolls at home on day 0
        "story": "",
    }


PROMPT = """Write a short life sketch for each household below, for use in a simulation set in Japan.
Each sketch is 2-3 sentences in plain English: who they are, one or two concrete details of their daily life or past,
and how they tend to react when shops run short of something or when rumours spread. Make them different from each other:
some calm, some stubborn, some generous, some selfish, some distrustful of the media, some who remember past shortages.
Stay consistent with the given attributes (the numbers 0-1 are: anxiety = worries easily, conformity = follows others,
trust = believes official statements). Do not mention toilet paper, any year, or any specific disease.
Reply with ONE JSON object: {"stories": {"<id>": "<sketch>", ...}} covering every id.

HOUSEHOLDS:
"""


async def main():
    rng = random.Random(2020)
    people = [draw(rng, i) for i in range(N)]
    llm = make_llm(load_settings())
    if not llm.live:
        raise SystemExit("needs OPENAI_API_KEY")
    tin = tout = 0

    async def batch(rows):
        nonlocal tin, tout
        brief = [{k: r[k] for k in ("id", "kind", "age", "work", "area", "info_text", "anxiety", "conformity", "trust")} | {"name": r["name"]["en"]} for r in rows]
        data, results = await chat_json(llm, "agent", [{"role": "user", "content": PROMPT + json.dumps(brief, ensure_ascii=False)}], max_tokens=6000)
        tin += sum(x.tokens_in for x in results)
        tout += sum(x.tokens_out for x in results)
        for r in rows:
            r["story"] = str((data.get("stories") or {}).get(str(r["id"]), "")).strip()

    await asyncio.gather(*(batch(people[i:i + 20]) for i in range(0, N, 20)))
    missing = [r["id"] for r in people if not r["story"]]
    await llm.close()
    OUT.write_text(json.dumps({"households": people}, ensure_ascii=False, indent=1) + "\n")
    print(f"{N} households written to {OUT.name}; stories missing: {len(missing)}; tokens {tin:,} in / {tout:,} out")


if __name__ == "__main__":
    asyncio.run(main())
