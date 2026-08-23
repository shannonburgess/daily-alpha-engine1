from __future__ import annotations

import argparse
import json
from pathlib import Path

from daily_alpha.pine_paired_evidence_capture import render_paired_capture_skeleton


def render(*, symbol: str, output: Path) -> dict[str, object]:
    packet = render_paired_capture_skeleton(symbol)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the exact SH24/SH25 TradingView parity evidence capture packet."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = render(symbol=args.symbol, output=args.output)
    print(
        json.dumps(
            {
                "packet_id": packet["packet_id"],
                "symbol": packet["symbol"],
                "trading_authorized": False,
                "live_trading_enabled": False,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
