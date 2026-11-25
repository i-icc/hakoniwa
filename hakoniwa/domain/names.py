"""Names for residents. When several residents share one description (the same
agent in the spec), each gets a name of its own so the observer can tell them
apart. Names depend only on the order in which residents first appear, so a
run always shows the same names. Pure functions."""
from __future__ import annotations

from typing import Any

POOL = [
    ("Yamada", "山田"), ("James", "ジェームズ"), ("Sato", "佐藤"), ("Maria", "マリア"), ("Suzuki", "鈴木"), ("Chen", "チェン"),
    ("Tanaka", "田中"), ("Aisha", "アイシャ"), ("Takahashi", "高橋"), ("Lucas", "ルーカス"), ("Ito", "伊藤"), ("Priya", "プリヤ"),
    ("Watanabe", "渡辺"), ("Omar", "オマール"), ("Nakamura", "中村"), ("Sofia", "ソフィア"), ("Kobayashi", "小林"), ("Minh", "ミン"),
    ("Kato", "加藤"), ("Emma", "エマ"), ("Yoshida", "吉田"), ("Diego", "ディエゴ"), ("Yamamoto", "山本"), ("Fatima", "ファティマ"),
    ("Sasaki", "佐々木"), ("Noah", "ノア"), ("Matsumoto", "松本"), ("Hana", "ハナ"), ("Inoue", "井上"), ("Ivan", "イワン"),
    ("Kimura", "木村"), ("Chloe", "クロエ"), ("Hayashi", "林"), ("Arjun", "アルジュン"), ("Shimizu", "清水"), ("Layla", "ライラ"),
    ("Mori", "森"), ("Ethan", "イーサン"), ("Abe", "阿部"), ("Mei", "メイ"), ("Ikeda", "池田"), ("Pedro", "ペドロ"),
    ("Hashimoto", "橋本"), ("Nora", "ノラ"), ("Ishikawa", "石川"), ("Kwame", "クワメ"), ("Ogawa", "小川"), ("Elena", "エレナ"),
    ("Maeda", "前田"), ("Tom", "トム"), ("Fujita", "藤田"), ("Yuna", "ユナ"), ("Okada", "岡田"), ("Samir", "サミール"),
    ("Goto", "後藤"), ("Anna", "アンナ"), ("Hasegawa", "長谷川"), ("Leo", "レオ"), ("Murakami", "村上"), ("Zoe", "ゾーイ"),
    ("Kondo", "近藤"), ("Raj", "ラジ"), ("Ishii", "石井"), ("Clara", "クララ"), ("Sakamoto", "坂本"), ("Felix", "フェリックス"),
    ("Endo", "遠藤"), ("Amira", "アミーラ"), ("Aoki", "青木"), ("Oscar", "オスカー"), ("Fujii", "藤井"), ("Lina", "リナ"),
    ("Nishimura", "西村"), ("Hugo", "ヒューゴ"), ("Fukuda", "福田"), ("Sara", "サラ"), ("Ota", "太田"), ("Mateo", "マテオ"),
    ("Miura", "三浦"), ("Ines", "イネス"), ("Okamoto", "岡本"), ("Viktor", "ヴィクトル"), ("Matsuda", "松田"), ("Nadia", "ナディア"),
    ("Nakagawa", "中川"), ("Ben", "ベン"), ("Nakano", "中野"), ("Rosa", "ローザ"), ("Harada", "原田"), ("Kofi", "コフィ"),
    ("Ono", "小野"), ("Greta", "グレタ"), ("Tamura", "田村"), ("Luis", "ルイス"), ("Takeuchi", "竹内"), ("Aiko", "アイコ"),
]


def pool_name(i: int) -> dict:
    en, ja = POOL[i % len(POOL)]
    lap = i // len(POOL)
    return {"en": en + (f" {lap + 1}" if lap else ""), "ja": ja + (f" {lap + 1}" if lap else "")}


def _given(v: Any) -> dict | None:
    if isinstance(v, str) and v.strip():
        return {"en": v.strip(), "ja": v.strip()}
    if isinstance(v, dict) and v.get("en"):
        return {"en": str(v["en"]), "ja": str(v.get("ja") or v["en"])}
    return None


def resident_names(spec: dict, residents: list[dict]) -> dict[str, dict | None]:
    """residents: [{key, agent, given}] in order of first appearance -> {key: {en, ja} or None}.

    A name the model supplied wins. A resident who is the only one of its kind
    and is defined as an individual keeps the name from the spec (None here).
    Everyone else takes the pool name at their position, which never changes."""
    kinds = {a["id"]: a.get("kind") for a in spec.get("agents", [])}
    count: dict[str, int] = {}
    for r in residents:
        count[r["agent"]] = count.get(r["agent"], 0) + 1
    out: dict[str, dict | None] = {}
    for i, r in enumerate(residents):
        given = _given(r.get("given"))
        if given:
            out[r["key"]] = given
        elif kinds.get(r["agent"]) == "individual" and count[r["agent"]] == 1:
            out[r["key"]] = None
        else:
            out[r["key"]] = pool_name(i)
    return out


def display_name(name: dict | None, population: Any) -> dict | None:
    """A group is shown as "Yamada's group" / "山田さんたち"."""
    if not name:
        return None
    try:
        many = population is not None and float(population) > 1
    except (TypeError, ValueError):
        many = False
    return {"en": f"{name['en']}'s group", "ja": f"{name['ja']}さんたち"} if many else name
