import argparse

from app.config import RISK_PROFILES
from backtest.replay import load_ws_rows, resolve_stake_usd, run_replay


def _fmt(res):
    return (
        f"opened={res['opened']} closed={res['closed']} win_rate={res['win_rate']:.2f}% "
        f"exp={res['expectancy_pct']:+.4f} pf={res['profit_factor']:.2f} "
        f"pnl_usd={res['total_pnl_usd']:+.2f} forced={res['forced_closes']}"
    )


def _delta(a, b, key):
    return float(b.get(key, 0.0)) - float(a.get(key, 0.0))


def _diag_line(res):
    d = res.get("diagnostics", {})
    align = d.get("resolved_alignment_rate", {})
    sl = d.get("sl_impact", {})
    return (
        f"align={align.get('overall_pct', 0.0):.2f}% "
        f"sl_saved={sl.get('saved_loss_total_usd', 0.0):+.2f} "
        f"sl_cut={sl.get('cut_winner_total_usd', 0.0):+.2f}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="A/B replay comparison for two risk profiles."
    )
    parser.add_argument("--profile-a", default="MAIN", help="Baseline profile name")
    parser.add_argument("--profile-b", default="MAIN_HOLD", help="Variant profile name")
    parser.add_argument(
        "--rows-limit",
        type=int,
        default=0,
        help="Use only latest N ws rows (0=all)",
    )
    parser.add_argument("--start-ts-ms", type=int, default=None)
    parser.add_argument("--end-ts-ms", type=int, default=None)
    parser.add_argument("--latency-ms", type=int, default=250)
    parser.add_argument("--extra-slippage", type=float, default=0.001)
    args = parser.parse_args()

    profile_a = RISK_PROFILES.get(args.profile_a)
    profile_b = RISK_PROFILES.get(args.profile_b)
    if not profile_a:
        raise ValueError(f"Unknown profile-a: {args.profile_a}")
    if not profile_b:
        raise ValueError(f"Unknown profile-b: {args.profile_b}")

    rows_a = load_ws_rows(
        profile_a,
        start_ts_ms=args.start_ts_ms,
        end_ts_ms=args.end_ts_ms,
        rows_limit=args.rows_limit,
    )
    if not rows_a:
        print("No ws_ticks rows found for profile A filters.")
        return

    rows_b = load_ws_rows(
        profile_b,
        start_ts_ms=args.start_ts_ms,
        end_ts_ms=args.end_ts_ms,
        rows_limit=args.rows_limit,
    )
    if not rows_b:
        print("No ws_ticks rows found for profile B filters.")
        return

    stake_usd = resolve_stake_usd(default_value=10.0)
    result_a = run_replay(
        rows_a,
        profile_a,
        stake_usd=stake_usd,
        latency_ms=args.latency_ms,
        extra_slippage=args.extra_slippage,
    )
    result_b = run_replay(
        rows_b,
        profile_b,
        stake_usd=stake_usd,
        latency_ms=args.latency_ms,
        extra_slippage=args.extra_slippage,
    )

    print(
        f"A/B replay | stake={stake_usd:.2f} | rows_a={len(rows_a)} rows_b={len(rows_b)}"
    )
    print(f"A ({args.profile_a}) -> {_fmt(result_a)}")
    print(f"  diagnostics -> {_diag_line(result_a)}")
    print(f"B ({args.profile_b}) -> {_fmt(result_b)}")
    print(f"  diagnostics -> {_diag_line(result_b)}")

    print("\nDelta (B - A)")
    print(f"closed_trades: {_delta(result_a, result_b, 'closed'):+.0f}")
    print(f"win_rate_pct: {_delta(result_a, result_b, 'win_rate'):+.2f}")
    print(f"expectancy_pct: {_delta(result_a, result_b, 'expectancy_pct'):+.4f}")
    print(f"profit_factor: {_delta(result_a, result_b, 'profit_factor'):+.2f}")
    print(f"total_pnl_usd: {_delta(result_a, result_b, 'total_pnl_usd'):+.2f}")
    print(f"forced_closes: {_delta(result_a, result_b, 'forced_closes'):+.0f}")


if __name__ == "__main__":
    main()
