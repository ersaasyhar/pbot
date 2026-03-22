class Trade:
    def __init__(self, side, entry_price):
        self.side = side  # BUY YES / BUY NO
        self.entry = entry_price
        self.open = True

    def pnl(self, current_price):
        if self.side == "BUY YES":
            # Profit if price goes UP
            return current_price - self.entry
        else:  # BUY NO
            # Profit if price goes DOWN (YES probability decreases)
            return self.entry - current_price
