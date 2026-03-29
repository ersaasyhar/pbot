import argparse

from app.config import RISK_PROFILES
from backtest.replay import load_ws_rows, resolve_stake_usd, run_replay


def merged_loader_profile(profile_a, profile_b):
    a_coins = set([str(c).lower() for c in profile_a.get("trade_allowed_coins", [])])
    b_coins = set([str(c).lower() for c in profile_b.get("trade_allowed_coins", [])])
    a_tfs = set([str(tf) for tf in profile_a.get("trade_allowed_timeframes", [])])
    b_tfs = set([str(tf) for tf in profile_b.get("trade_allowed_timeframes", [])])
    a_ctfs = set([str(tf) for tf in profile_a.get("confirmation_timeframes", [])])
    b_ctfs = set([str(tf) for tf in profile_b.get("confirmation_timeframes", [])])
    return {
        "trade_allowed_coins": sorted(a_coins | b_coins),
        "trade_allowed_timeframes": sorted(a_tfs | b_tfs | a_ctfs | b_ctfs),
        "confirmation_timeframes": [],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward A/B compare across rolling windows."
    )
    parser.add_argument("--profile-a", default="MAIN", help="Baseline profile")
    parser.add_argument("--profile-b", default="MAIN_HOLD", help="Variant profile")
    parser.add_argument("--rows-limit", type=int, default=0, help="0=all rows")
    parser.add_argument("--folds", type=int, default=6, help="Number of OOS folds")
    parser.add_argument(
        "--min-closed-test",
        type=int,
        default=3,
        help="Only score fold if both profiles have at least this many closed trades",
    )
    parser.add_argument("--latency-ms", type=int, default=250)
    parser.add_argument("--extra-slippage", type=float, default=0.001)
    args = parser.parse_args()

    profile_a = RISK_PROFILES.get(args.profile_a)
    profile_b = RISK_PROFILES.get(args.profile_b)
    if not profile_a:
        raise ValueError(f"Unknown profile-a: {args.profile_a}")
    if not profile_b:
        raise ValueError(f"Unknown profile-b: {args.profile_b}")

    loader_profile = merged_loader_profile(profile_a, profile_b)
    rows = load_ws_rows(loader_profile, rows_limit=args.rows_limit)
    if not rows:
        print("❌ No ws_ticks rows found for walk-forward A/B.")
        return
    if args.folds < 1:
        print("❌ --folds must be >= 1")
        return

    n = len(rows)
    block = n // (args.folds + 1)
    if block < 500:
        print(f"❌ Not enough rows for walk-forward A/B: rows={n}, folds={args.folds}.")
        return

    stake_usd = resolve_stake_usd(default_value=10.0)
    considered = []
    skipped = 0
    print(
        f"🧪 WALK-FORWARD A/B | A={args.profile_a} B={args.profile_b} | "
        f"rows={n} folds={args.folds} min_closed_test={args.min_closed_test}"
    )

    for fold in range(1, args.folds + 1):
        train_end = block * fold
        test_end = min(train_end + block, n)
        test_rows = rows[train_end:test_end]
        if not test_rows:
            break

        res_a = run_replay(
            test_rows,
            dict(profile_a),
            stake_usd=stake_usd,
            latency_ms=args.latency_ms,
            extra_slippage=args.extra_slippage,
        )
        res_b = run_replay(
            test_rows,
            dict(profile_b),
            stake_usd=stake_usd,
            latency_ms=args.latency_ms,
            extra_slippage=args.extra_slippage,
        )

        closed_a = int(res_a.get("closed", 0))
        closed_b = int(res_b.get("closed", 0))
        if closed_a < args.min_closed_test or closed_b < args.min_closed_test:
            skipped += 1
            print(
                f"[Fold {fold}] skipped: closed_a={closed_a} closed_b={closed_b} (<{args.min_closed_test})"
            )
            continue

        row = {
            "fold": fold,
            "a": res_a,
            "b": res_b,
            "delta_pnl_usd": float(res_b["total_pnl_usd"])
            - float(res_a["total_pnl_usd"]),
            "delta_exp": float(res_b["expectancy_pct"])
            - float(res_a["expectancy_pct"]),
            "delta_pf": float(res_b["profit_factor"]) - float(res_a["profit_factor"]),
        }
        considered.append(row)
        print(
            f"[Fold {fold}] A(closed={closed_a}, pnl={res_a['total_pnl_usd']:+.2f}, exp={res_a['expectancy_pct']:+.4f}, pf={res_a['profit_factor']:.2f}) | "
            f"B(closed={closed_b}, pnl={res_b['total_pnl_usd']:+.2f}, exp={res_b['expectancy_pct']:+.4f}, pf={res_b['profit_factor']:.2f}) | "
            f"Δpnl={row['delta_pnl_usd']:+.2f} Δexp={row['delta_exp']:+.4f} Δpf={row['delta_pf']:+.2f}"
        )

    print("\n" + "=" * 64)
    print("WALK-FORWARD A/B SUMMARY (OOS)")
    print("=" * 64)
    print(f"Total folds: {args.folds}")
    print(f"Considered folds: {len(considered)}")
    print(f"Skipped folds: {skipped}")
    if not considered:
        print("No folds met minimum trade count threshold.")
        return

    b_better_pnl = sum(1 for r in considered if r["delta_pnl_usd"] > 0)
    b_better_exp = sum(1 for r in considered if r["delta_exp"] > 0)
    b_better_pf = sum(1 for r in considered if r["delta_pf"] > 0)
    med_delta_pnl = sorted([r["delta_pnl_usd"] for r in considered])[
        len(considered) // 2
    ]
    med_delta_exp = sorted([r["delta_exp"] for r in considered])[len(considered) // 2]
    med_delta_pf = sorted([r["delta_pf"] for r in considered])[len(considered) // 2]

    print(f"B better pnl folds: {b_better_pnl}/{len(considered)}")
    print(f"B better expectancy folds: {b_better_exp}/{len(considered)}")
    print(f"B better PF folds: {b_better_pf}/{len(considered)}")
    print(f"Median delta pnl (B-A): {med_delta_pnl:+.2f} USD")
    print(f"Median delta expectancy (B-A): {med_delta_exp:+.4f}")
    print(f"Median delta PF (B-A): {med_delta_pf:+.2f}")


if __name__ == "__main__":
    main()
