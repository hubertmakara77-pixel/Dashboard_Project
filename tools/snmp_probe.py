import argparse
import asyncio
import json
import pathlib

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)


def load_defaults() -> tuple[int, str]:
    path = pathlib.Path("data/persisted_state.json")
    if not path.exists():
        return 1161, ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    settings = payload.get("snmp_settings", {})
    return int(settings.get("port", 1161)), str(settings.get("community", ""))


async def probe(host: str, port: int, community: str) -> int:
    target = await UdpTransportTarget.create((host, port))
    error_indication, error_status, _error_index, var_binds = await get_cmd(
        SnmpEngine(),
        CommunityData(community),
        target,
        ContextData(),
        ObjectType(ObjectIdentity("1.3.6.1.4.1.99999.1.1.0")),
        ObjectType(ObjectIdentity("1.3.6.1.4.1.99999.2.1.0")),
        ObjectType(ObjectIdentity("1.3.6.1.4.1.99999.2.5.0")),
    )
    if error_indication:
        print(f"SNMP communication error: {error_indication}")
        return 1
    if error_status:
        print(f"SNMP response error: {error_status.prettyPrint()}")
        return 1
    for var_bind in var_binds:
        print(" = ".join(value.prettyPrint() for value in var_bind))
    return 0


def main() -> int:
    default_port, default_community = load_defaults()
    parser = argparse.ArgumentParser(description="Probe the amplifier SNMP agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--community", default=default_community)
    args = parser.parse_args()
    if not args.community:
        parser.error("SNMP community is required; pass --community or configure Amp Panel first")
    return asyncio.run(probe(args.host, args.port, args.community))


if __name__ == "__main__":
    raise SystemExit(main())
