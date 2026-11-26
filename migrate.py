"""
اسکریپت مهاجرت یک‌باره.
list.json قدیمی را به ساختار جدید (با last_seen و dedup بر اساس (ip, operator)) تبدیل می‌کند.
پس از اجرا، فایل قدیمی به list.json.bak منتقل می‌شود.
"""

import json
import os
import shutil
import time
from datetime import datetime

OLD = "list.json"
BACKUP = "list.json.bak"


def main():
    if not os.path.exists(OLD):
        print(f"[!] فایل {OLD} یافت نشد.")
        return

    with open(OLD, encoding="utf-8") as f:
        old_data = json.load(f)

    old_ipv4 = old_data.get("ipv4", [])
    old_ipv6 = old_data.get("ipv6", [])

    # آخرین last_seen تقریبی: بزرگ‌ترین created_at یا last_timestamp قبلی
    fallback_seen = old_data.get("last_timestamp") or int(time.time())
    if old_ipv4:
        fallback_seen = max(fallback_seen, max(el["created_at"] for el in old_ipv4))

    def dedup(items):
        seen = {}
        for el in items:
            key = (el["ip"], el["operator"])
            if key in seen:
                # قدیمی‌ترین created_at را نگه می‌داریم
                if el["created_at"] < seen[key]["created_at"]:
                    seen[key]["created_at"] = el["created_at"]
                # provider جدید را در صورت وجود نگه می‌داریم (اولی)
                continue
            seen[key] = {
                "ip": el["ip"],
                "operator": el["operator"],
                "provider": el.get("provider", ""),
                "created_at": el["created_at"],
                "last_seen": el.get("last_seen", fallback_seen),
            }
        out = list(seen.values())
        out.sort(key=lambda e: (e["operator"], -e["created_at"]))
        return out

    new_ipv4 = dedup(old_ipv4)
    new_ipv6 = dedup(old_ipv6)

    new_data = {
        "last_update": datetime.fromtimestamp(fallback_seen).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "last_timestamp": fallback_seen,
        "ipv4": new_ipv4,
        "ipv6": new_ipv6,
    }

    shutil.copy2(OLD, BACKUP)
    with open(OLD, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=4, ensure_ascii=False)

    print(f"[✓] مهاجرت انجام شد. نسخه پشتیبان: {BACKUP}")
    print(f"    IPv4: {len(old_ipv4)} → {len(new_ipv4)}")
    print(f"    IPv6: {len(old_ipv6)} → {len(new_ipv6)}")


if __name__ == "__main__":
    main()