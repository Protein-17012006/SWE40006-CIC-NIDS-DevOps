"""Readable names for the destination ports and protocol numbers the pages show."""

SERVICE_NAMES: dict[int, str] = {
    0: "no port",
    21: "FTP",
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    123: "NTP",
    139: "NetBIOS",
    443: "HTTPS",
    445: "SMB",
    3389: "RDP",
    8080: "HTTP alt",
}
PROTOCOL_NAMES: dict[int, str] = {6: "TCP", 17: "UDP", 1: "ICMP"}
# Ingestion keeps the top 50 ports per day, category and protocol and sums the rest here
OTHER_PORT = -1


def port_label(port: int) -> str:
    if port == OTHER_PORT:
        return "other"
    name = SERVICE_NAMES.get(port)
    return f"{port} · {name}" if name else str(port)


def protocol_name(number: int) -> str:
    return PROTOCOL_NAMES.get(number, "Other")
