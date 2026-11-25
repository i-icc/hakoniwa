"""Token and cost arithmetic. Pure functions over the price table (prices.json)."""
from __future__ import annotations


def approx_tokens(text: str) -> int:
    """Rough token count for estimates: ~4 chars/token for Latin text, ~1.5 for CJK."""
    cjk = sum(1 for ch in text if ord(ch) > 0x2E7F)
    return int((len(text) - cjk) / 4 + cjk / 1.5) + 1


def price_for(prices: dict, model: str) -> dict | None:
    """Longest-prefix match of a model id against the price table."""
    models = (prices or {}).get("models", {})
    if model in models:
        return models[model]
    best = None
    for k, v in models.items():
        if model.startswith(k) and (best is None or len(k) > len(best[0])):
            best = (k, v)
    return best[1] if best else None


def cost_usd(prices: dict, model: str, tokens_in: int, tokens_out: int) -> float | None:
    """Cost of one call, or None when the model has no price entry."""
    p = price_for(prices, model)
    if not p:
        return None
    return tokens_in / 1e6 * p["in"] + tokens_out / 1e6 * p["out"]
