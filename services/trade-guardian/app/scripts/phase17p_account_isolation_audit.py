from __future__ import annotations
import argparse, json
from guardian_account_isolation import fetch_guardian_account_isolation_audit

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(fetch_guardian_account_isolation_audit(args.account_id), indent=2, default=str))

if __name__ == "__main__":
    main()
