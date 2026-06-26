# Neewer WiFi — Home Assistant Integration

Home Assistant custom integration for Neewer GL1 Pro WiFi key lights, distributed via HACS.

Controls lights over the reverse-engineered UDP protocol on port **5052** ([braintapper/neewer-gl1](https://github.com/braintapper/neewer-gl1), [mglatt/neewer-wifi-python](https://github.com/mglatt/neewer-wifi-python)). Includes **subnet auto-discovery** so you do not need to enter IP addresses manually.

## Tested device

- **Neewer GL1 Pro** (WiFi control path)

Other Neewer WiFi models that share the same UDP protocol may work but are not verified.

## Features

- HACS installable custom component
- Config flow with local subnet discovery (UDP handshake probe)
- Manual IP fallback when discovery fails
- One `light` entity per device: on/off, brightness, color temperature (2900K–7000K)
- Shared UDP session management with heartbeat and periodic re-handshake

## Installation (HACS)

1. Open **HACS** → **Integrations** → **Custom repositories**
2. Add repository URL: `https://github.com/MrCurlsTTV/hacs-neweer-gl1`
3. Category: **Integration**
4. Install **Neewer WiFi**
5. Restart Home Assistant
6. Go to **Settings** → **Devices & Services** → **Add Integration** → **Neewer WiFi**

## Manual installation

Copy `custom_components/neewer_wifi` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

## Usage

1. Add the integration and choose **Discover lights on local network** (scan may take 10–30 seconds on a typical `/24` subnet).
2. Select one or more discovered lights, or use **Enter light IP manually**.
3. Each light appears as a `light` entity (e.g. `light.neewer_gl1_pro_142`).

### Entity attributes (example)

```yaml
light.neewer_gl1_pro_142:
  state: on
  brightness: 128
  color_temp_kelvin: 5600
  supported_color_modes:
    - color_temp
  min_color_temp_kelvin: 2900
  max_color_temp_kelvin: 7000
```

## Discovery behavior

Discovery enumerates **private RFC1918** IPv4 subnets from Home Assistant network adapters, then probes each host with:

1. UDP handshake (client IP embedded, checksummed)
2. Wakeup packet
3. Heartbeat packet

A host is identified as a Neewer light when a plausible protocol response is received (heartbeat ack `80 03 00 83`). Probes use ephemeral source ports with limited concurrency (30 workers) and per-host timeouts (~2s).

Discovery does **not** require DHCP reservations, but a stable IP helps avoid stale entries after network changes.

## Session conflict

Only **one controller** can hold the UDP session per light at a time. Close the Neewer mobile/desktop app before using Home Assistant. If commands stop working, reload the integration or restart Home Assistant to re-handshake.

## No device-reported state

The light does not report its state over UDP. The integration tracks state locally. Physical button changes or other apps will desync entity state until you toggle from Home Assistant again.

## Troubleshooting

| Issue | Action |
|-------|--------|
| Discovery finds nothing | Confirm light is on WiFi; try manual IP; ensure HA host is on the same LAN/subnet |
| Cannot connect | Close Neewer app; reload integration |
| Port 5052 in use | Another process bound UDP 5052; stop conflicting service |
| Wrong brightness/temp | State is local-only; turn light off/on from HA to resync |

## Development

```bash
# Protocol / discovery unit tests (no HA runtime required)
python -m pytest tests/ -v

# Lint (optional)
ruff check custom_components tests
```

### Manual test plan

- [ ] Install via HACS or manual copy; restart HA
- [ ] Add integration → Discover → wait for scan; at least one GL1 Pro listed
- [ ] Select light → entity appears under Devices
- [ ] Turn off / on from HA UI
- [ ] Adjust brightness slider
- [ ] Adjust color temperature
- [ ] Add second light via Discover (multi-select or second add)
- [ ] Manual path: enter IP when discovery disabled or light on different subnet
- [ ] Reload integration; entity remains and controls work
- [ ] Open Neewer app while HA controls → expect conflict; close app and reload integration

## Credits

- [braintapper/neewer-gl1](https://github.com/braintapper/neewer-gl1) — UDP protocol
- [mglatt/neewer-wifi-python](https://github.com/mglatt/neewer-wifi-python) — Python reference server

## License

MIT
