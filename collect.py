import json
import logging
import time
from datetime import datetime

import dns.exception
import dns.resolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("collect")

LIST_JSON = "list.json"
LIST_TXT = "list.txt"
PROVIDERS_JSON = "providers.json"

DNS_TIMEOUT = 2
DNS_LIFETIME = 2


def load_json_safe(path, default):
    """فایل JSON را با تحمل خطا بارگذاری می‌کند."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning("فایل %s یافت نشد؛ از مقدار پیش‌فرض استفاده می‌شود.", path)
        return default
    except json.JSONDecodeError as exc:
        log.error("خطا در پارس کردن %s: %s — از مقدار پیش‌فرض استفاده می‌شود.", path, exc)
        return default


def load_existing():
    """لیست قبلی را با ساختار استاندارد برمی‌گرداند."""
    data = load_json_safe(LIST_JSON, {"ipv4": [], "ipv6": []})
    return {
        "ipv4": data.get("ipv4", []) if isinstance(data, dict) else [],
        "ipv6": data.get("ipv6", []) if isinstance(data, dict) else [],
    }


def resolve(provider, rtype, resolver):
    """درخواست DNS را انجام می‌دهد و در صورت خطا لیست خالی برمی‌گرداند."""
    try:
        answers = resolver.resolve(provider, rtype)
        return [ans.to_text() for ans in answers]
    except dns.resolver.NXDOMAIN:
        log.warning("[%s] %s: دامنه وجود ندارد (NXDOMAIN).", rtype, provider)
    except dns.resolver.NoAnswer:
        log.warning("[%s] %s: پاسخی برای این نوع رکورد وجود ندارد.", rtype, provider)
    except dns.resolver.NoNameservers:
        log.warning("[%s] %s: هیچ نیم‌سرور معتبری پاسخ نداد.", rtype, provider)
    except dns.resolver.LifetimeTimeout:
        log.warning("[%s] %s: مهلت درخواست به پایان رسید.", rtype, provider)
    except dns.exception.DNSException as exc:
        log.warning("[%s] %s: خطای DNS: %s", rtype, provider, exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("[%s] %s: خطای غیرمنتظره: %s", rtype, provider, exc)
    return []


def build_records(resolved, existing_map, operator, provider, rtype, now):
    """رکوردهای جدید/به‌روز را از نتیجه‌ی DNS تولید می‌کند.

    کلید یکتا: (ip, operator, rtype)
    """
    provider_short = ".".join(provider.split(".")[1:]) or provider
    records = []
    seen = set()

    for ip in resolved:
        key = (ip, operator, rtype)
        if key in seen:
            continue
        seen.add(key)

        prev = existing_map.get(key)
        created_at = prev["created_at"] if prev else now
        records.append(
            {
                "ip": ip,
                "operator": operator,
                "provider": provider_short,
                "created_at": created_at,
                "last_seen": now,
                "type": rtype,
            }
        )
    return records


def collect():
    providers = load_json_safe(PROVIDERS_JSON, {})
    if not isinstance(providers, dict) or not providers:
        log.error("فایل providers.json خالی یا نامعتبر است.")
        return {
            "last_update": "",
            "last_timestamp": 0,
            "ipv4": [],
            "ipv6": [],
        }

    existing = load_existing()

    # نگاشت کلید یکتا به رکورد قبلی، جدا برای IPv4 و IPv6
    existing_ipv4 = {(el["ip"], el["operator"]): el for el in existing["ipv4"]}
    existing_ipv6 = {(el["ip"], el["operator"]): el for el in existing["ipv6"]}

    resolver = dns.resolver.Resolver()
    resolver.timeout = DNS_TIMEOUT
    resolver.lifetime = DNS_LIFETIME

    now = int(time.time())
    ipv4_all, ipv6_all = [], []

    for provider, operator in providers.items():
        log.info("در حال resolve: %s (%s)", provider, operator)

        v4 = resolve(provider, "A", resolver)
        v6 = resolve(provider, "AAAA", resolver)

        ipv4_all.extend(
            build_records(v4, existing_ipv4, operator, provider, "ipv4", now)
        )
        ipv6_all.extend(
            build_records(v6, existing_ipv6, operator, provider, "ipv6", now)
        )

    # مرتب‌سازی: ابتدا بر اساس operator، سپس جدیدترین created_at
    ipv4_all.sort(key=lambda el: (el["operator"], -el["created_at"]))
    ipv6_all.sort(key=lambda el: (el["operator"], -el["created_at"]))

    # حذف فیلد کمکی type از خروجی JSON (فقط برای dedup داخلی بود)
    for el in ipv4_all:
        el.pop("type", None)
    for el in ipv6_all:
        el.pop("type", None)

    return {
        "last_update": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "last_timestamp": now,
        "ipv4": ipv4_all,
        "ipv6": ipv6_all,
    }


def write_outputs(result):
    with open(LIST_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)

    with open(LIST_TXT, "w", encoding="utf-8") as f:
        f.write(f"Last Update: {result['last_update']}\n")
        f.write(f"Total IPv4: {len(result['ipv4'])}\n")
        f.write(f"Total IPv6: {len(result['ipv6'])}\n\n")

        f.write("IPv4:\n")
        for el in result["ipv4"]:
            f.write(
                f"  - {el['ip']:39s}  {el['operator']:4s}  "
                f"{el['provider']:<24s}  "
                f"created={el['created_at']}  last_seen={el['last_seen']}\n"
            )

        f.write("\nIPv6:\n")
        for el in result["ipv6"]:
            f.write(
                f"  - {el['ip']:39s}  {el['operator']:4s}  "
                f"{el['provider']:<24s}  "
                f"created={el['created_at']}  last_seen={el['last_seen']}\n"
            )


def main():
    log.info("شروع جمع‌آوری...")
    result = collect()
    write_outputs(result)
    log.info(
        "پایان. %d IPv4 و %d IPv6 ثبت شد.",
        len(result["ipv4"]),
        len(result["ipv6"]),
    )


if __name__ == "__main__":
    main()