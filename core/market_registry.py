def upsert_active_markets(state, markets):
    new_tokens = []
    for market in markets:
        token_id = market.get("clob_token_id")
        if not token_id:
            continue

        key = f"{market.get('coin', '')}-{market.get('timeframe', '')}"
        prev_token_id = state.active_market_by_key.get(key)

        # Keep only one active contract per coin-timeframe key.
        if prev_token_id and prev_token_id != token_id:
            state.active_markets.pop(prev_token_id, None)

        state.active_market_by_key[key] = token_id
        state.active_markets[token_id] = market

        if token_id not in state.subscribed_tokens:
            new_tokens.append(token_id)
            state.subscribed_tokens.add(token_id)
    return new_tokens
