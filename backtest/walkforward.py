import argparse
import itertools
import math

from app.config import RISK_PROFILES, SELECTED_RISK_PROFILE_NAME
from backtest.replay import load_ws_rows, resolve_stake_usd, run_replay


def parse_float_list(raw):
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_int_list(raw):
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def score_metrics(metrics, min_closed):
    closed = int(metrics.get("closed", 0))
    if closed < min_closed:
        return -1e9
    expectancy = float(metrics.get("expectancy_pct", 0.0))
    return expectancy * math.sqrt(max(1, closed))


def best_params_on_train(
    train_rows,
    base_profile,
    stake_usd,
    latency_ms,
    extra_slippage,
    grid_min_ev,
    grid_decay,
    grid_age,
    grid_topn,
    min_closed_train,
):
    combos = list(itertools.product(grid_min_ev, grid_decay, grid_age, grid_topn))
    best = None
    for min_ev, decay, age, topn in combos:
        profile = dict(base_profile)
        profile["min_effective_ev"] = float(min_ev)
        profile["signal_decay_lambda"] = float(decay)
        profile["max_signal_age_sec"] = int(age)
        profile["max_entries_per_cycle"] = int(topn)
        res = run_replay(
            train_rows,
            profile,
            stake_usd=stake_usd,
            latency_ms=latency_ms,
            extra_slippage=extra_slippage,
        )
        sc = score_metrics(res, min_closed_train)
        row = {
            "min_effective_ev": float(min_ev),
            "signal_decay_lambda": float(decay),
            "max_signal_age_sec": int(age),
            "max_entries_per_cycle": int(topn),
            "score": sc,
            "train": res,
        }
        if best is None or row["score"] > best["score"]:
            best = row
    return best


def main():
    parser = argparse.ArgumentParser(description="Walk-forward tuning with ws replay.")
    parser.add_argument(
        "--profile",
        default=SELECTED_RISK_PROFILE_NAME,
        help="Risk profile from config",
    )
    parser.add_argument(
        "--rows-limit",
        type=int,
        default=120000,
        help="Use only latest N ws rows (0=all)",
    )
    parser.add_argument(
        "--folds",
        type=int,
        default=3,
        help="Number of forward-validation folds",
    )
    parser.add_argument("--min-ev", default="0.015,0.020,0.025")
    parser.add_argument("--decay", default="0.008,0.012")
    parser.add_argument("--age", default="45,60,90")
    parser.add_argument("--topn", default="1,2")
    parser.add_argument(
        "--min-closed-train",
        type=int,
        default=10,
        help="Minimum closed trades required in train for a combo to be valid",
    )
    parser.add_argument("--latency-ms", type=int, default=250)
    parser.add_argument("--extra-slippage", type=float, default=0.001)
    args = parser.parse_args()

    base_profile = RISK_PROFILES.get(args.profile, RISK_PROFILES.get("BALANCED", {}))
    rows = load_ws_rows(base_profile, rows_limit=args.rows_limit)
    if not rows:
        print("❌ No ws_ticks rows found. Run collector first to build replay dataset.")
        return
    if args.folds < 1:
        print("❌ --folds must be >= 1")
        return

    n = len(rows)
    block = n // (args.folds + 1)
    if block < 500:
        print(
            f"❌ Not enough rows for walk-forward: rows={n}, folds={args.folds}. "
            "Collect more ws_ticks or reduce folds."
        )
        return

    stake_usd = resolve_stake_usd(default_value=10.0)
    grid_min_ev = parse_float_list(args.min_ev)
    grid_decay = parse_float_list(args.decay)
    grid_age = parse_int_list(args.age)
    grid_topn = parse_int_list(args.topn)

    print(
        f"🧪 WALK-FORWARD | profile={args.profile} | rows={n} | folds={args.folds} | "
        f"grid={len(grid_min_ev) * len(grid_decay) * len(grid_age) * len(grid_topn)} combos"
    )

    fold_results = []
    for fold in range(1, args.folds + 1):
        train_end = block * fold
        test_end = min(train_end + block, n)
        train_rows = rows[:train_end]
        test_rows = rows[train_end:test_end]
        if not test_rows:
            break

        best = best_params_on_train(
            train_rows,
            base_profile,
            stake_usd,
            args.latency_ms,
            args.extra_slippage,
            grid_min_ev,
            grid_decay,
            grid_age,
            grid_topn,
            args.min_closed_train,
        )
        tuned = dict(base_profile)
        tuned["min_effective_ev"] = best["min_effective_ev"]
        tuned["signal_decay_lambda"] = best["signal_decay_lambda"]
        tuned["max_signal_age_sec"] = best["max_signal_age_sec"]
        tuned["max_entries_per_cycle"] = best["max_entries_per_cycle"]
        test_res = run_replay(
            test_rows,
            tuned,
            stake_usd=stake_usd,
            latency_ms=args.latency_ms,
            extra_slippage=args.extra_slippage,
        )
        fold_results.append(
            {
                "fold": fold,
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
                "best": best,
                "test": test_res,
            }
        )

        print(
            f"[Fold {fold}] "
            f"best(min_ev={best['min_effective_ev']:.3f}, decay={best['signal_decay_lambda']:.3f}, "
            f"age={best['max_signal_age_sec']}, topN={best['max_entries_per_cycle']}) | "
            f"train_closed={best['train']['closed']} train_exp={best['train']['expectancy_pct']:+.4f} | "
            f"test_closed={test_res['closed']} test_win={test_res['win_rate']:.1f}% "
            f"test_exp={test_res['expectancy_pct']:+.4f} test_pnl={test_res['total_pnl_usd']:+.2f}"
        )

    if not fold_results:
        print("❌ Walk-forward could not produce any fold results.")
        return

    total_closed = sum(r["test"]["closed"] for r in fold_results)
    total_wins = sum(r["test"]["wins"] for r in fold_results)
    total_pnl_pct = sum(r["test"]["total_pnl_pct"] for r in fold_results)
    total_pnl_usd = sum(r["test"]["total_pnl_usd"] for r in fold_results)
    gp = sum(r["test"]["gross_profit_pct"] for r in fold_results)
    gl = sum(r["test"]["gross_loss_pct"] for r in fold_results)
    pf = (gp / gl) if gl > 0 else 99.0
    win_rate = (total_wins / total_closed * 100.0) if total_closed else 0.0
    expectancy = (total_pnl_pct / total_closed) if total_closed else 0.0

    print("\n" + "=" * 56)
    print("WALK-FORWARD OUT-OF-SAMPLE SUMMARY")
    print("=" * 56)
    print(f"Folds: {len(fold_results)}")
    print(f"Closed Trades: {total_closed}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Expectancy: {expectancy:+.4f} (pct per trade)")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Total PnL: {total_pnl_usd:+.2f} USD")


if __name__ == "__main__":
    main()
