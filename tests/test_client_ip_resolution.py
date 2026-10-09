"""Tests for resolving the client IP embedded in the handshake.

The light only answers when the ASCII client IP in the handshake matches the
packet's real source IP, so the resolved client IP must be whatever source
address the kernel will actually send from.
"""

from tests.conftest import route_line as _route_line


def test_alias_without_src_route_uses_address_kernel_sends_from(system) -> None:
    """An alias in the light's subnet is not used unless traffic really leaves from it.

    With the alias present but no `src=` host route, the kernel still sends from the
    main address; embedding the alias would make the light silently ignore us.
    """
    system.adapters = [("192.168.1.50", 24), ("192.168.103.200", 32)]
    system.routes = [
        _route_line("enp1s0", "192.168.1.0/24"),
        _route_line("enp1s0", "192.168.103.0/24", gateway="192.168.1.2"),
    ]
    system.iface_ips = {"enp1s0": ["192.168.1.50", "192.168.103.200"]}
    system.kernel_src = {"192.168.103.101": "192.168.1.50"}

    assert system.resolve("192.168.103.101") == "192.168.1.50"


def test_alias_with_src_host_route_uses_alias(system) -> None:
    """Routed-subnet setup: alias + `<light>/32 via <router> src=<alias>` embeds the alias."""
    system.adapters = [("192.168.1.50", 24), ("192.168.103.200", 32)]
    system.routes = [
        _route_line("enp1s0", "192.168.1.0/24"),
        _route_line("enp1s0", "192.168.103.0/24", gateway="192.168.1.2"),
    ]
    system.iface_ips = {"enp1s0": ["192.168.1.50", "192.168.103.200"]}
    system.kernel_src = {"192.168.103.101": "192.168.103.200"}

    assert system.resolve("192.168.103.101") == "192.168.103.200"


def test_falls_back_to_routing_table_when_kernel_cannot_route(system) -> None:
    """If the kernel lookup fails, a matching route table entry still yields a client IP."""
    system.adapters = [("192.168.1.50", 24)]
    system.routes = [_route_line("enp1s0", "192.168.103.0/24", gateway="192.168.1.2")]
    system.iface_ips = {"enp1s0": ["192.168.1.50"]}

    assert system.resolve("192.168.103.101") == "192.168.1.50"


def test_unroutable_host_resolves_to_none(system) -> None:
    """No kernel route and no matching adapter/route means no client IP."""
    system.adapters = [("192.168.1.50", 24)]

    assert system.resolve("192.168.103.101") is None
