# pico-octoprint

Turn a **Raspberry Pi Pico W** (or Pico 2 W) into a transparent serial-to-Wi-Fi bridge so [OctoPrint](https://octoprint.org/) can talk to a 3D printer over the network instead of a USB cable.

The Pico W joins your Wi-Fi, listens on a TCP port, and copies bytes in both directions between that socket and the printer UART. OctoPrint connects to the Pico as if it were a local serial port.

```
3D printer UART  <-->  Pico W  <-->  Wi-Fi  <-->  OctoPrint (socket://pico:8888)
```

Pico W firmware is **MicroPython**. USB on the Pico stays as the normal REPL, so you can configure Wi-Fi with Thonny or `mpremote`. The printer connection is the hardware UART (the Pico W cannot act as a USB host, so you do not plug the printer’s USB cable into the Pico).

## What you need

- Raspberry Pi Pico W or Pico 2 W
- A 3D printer that speaks G-code over serial (Marlin, Prusa, RepRapFirmware, and similar). This is **not** a Klipper MCU link; Klipper needs a direct USB/UART connection to the MCU.
- OctoPrint on the same LAN (Raspberry Pi, PC, or Docker)
- Four jumper wires (TX, RX, GND, and optionally 5 V for power)
- A **3.3 V** serial link, or a level shifter if the printer UART is 5 V
- 2.4 GHz Wi-Fi (the Pico W radio does not support 5 GHz)

## 1. Flash MicroPython

1. Download the UF2 for your board:
   - Pico W: [RPI_PICO_W](https://micropython.org/download/RPI_PICO_W/)
   - Pico 2 W: [RPI_PICO2_W](https://micropython.org/download/RPI_PICO2_W/)
2. Hold **BOOTSEL**, plug the Pico into USB, then release BOOTSEL.
3. Copy the UF2 onto the `RPI-RP2` drive. The board reboots into MicroPython.

## 2. Configure Wi-Fi and copy the firmware

On your computer, copy the example config and edit it:

```bash
cp src/config.example.py src/config.py
```

Set at least:

| Setting | Meaning |
| --- | --- |
| `WIFI_SSID` | 2.4 GHz network name |
| `WIFI_PASSWORD` | Network password |
| `WIFI_HOSTNAME` | DHCP / mDNS name (`pico-octoprint` by default) |
| `TCP_PORT` | Raw serial TCP port (`8888` by default) |
| `UART_BAUD` | Must match the printer (often `115200` or `250000`) |
| `STATIC_IP` | Optional `("192.168.1.50", "255.255.255.0", "192.168.1.1", "8.8.8.8")` |

Copy both files onto the Pico. With [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html):

```bash
mpremote connect auto cp src/main.py :main.py
mpremote connect auto cp src/config.py :config.py
mpremote connect auto reset
```

Or in [Thonny](https://thonny.org/): open `src/main.py` and `src/config.py`, and use **File → Save as → Raspberry Pi Pico** as `main.py` and `config.py`.

Open the USB serial console (Thonny shell or `mpremote connect auto repl`). You should see something like:

```
Wi-Fi: connected
  IP      192.168.1.50
TCP: listening on 192.168.1.50:8888 (raw serial)
OctoPrint: socket://192.168.1.50:8888
```

**Write down that IP** (and hostname if your router resolves it). You will paste it into OctoPrint.

### Onboard LED

| LED | Meaning |
| --- | --- |
| Fast blink | Joining Wi-Fi |
| Slow blink | Wi-Fi up, waiting for OctoPrint |
| Solid on | OctoPrint is connected |

## 3. Wire the Pico W to the printer

Pico GPIO is **3.3 V only**. Do not connect 5 V UART TX to a Pico RX pin without a level shifter (a 1 kΩ / 2 kΩ divider on RX is enough). Pico TX at 3.3 V is usually accepted by 5 V printer RX.

Default pins (UART1):

| Pico W | Printer |
| --- | --- |
| GP4 (TX) | RX |
| GP5 (RX) | TX |
| GND | GND |
| VSYS (optional) | 5 V (for power; USB also works) |

```
Printer TX ----> Pico GP5 (RX)
Printer RX <---- Pico GP4 (TX)
Printer GND ---- Pico GND
```

Where to tap serial on the printer:

- Many 32-bit boards have a dedicated UART / TFT / ESP header. Prefer a **3.3 V** header.
- On 8-bit AVR boards the USB-serial chip shares the same UART as the USB port. Unplug the printer USB cable from the computer when using this bridge.
- If serial looks like garbage, swap TX/RX, check baud, and try `UART_INVERT = True` (some Creality TFT headers invert the lines).

Power the Pico from USB (phone charger or the printer’s USB-A port if it supplies 5 V) or from printer 5 V into **VSYS**, never into a GPIO pin.

## 4. Connect the Pico W to the OctoPrint server

The Pico and the OctoPrint host must be on the **same LAN**. Client/guest Wi-Fi isolation, VLANs, and AP isolation will block the connection.

OctoPrint talks to the Pico over a raw TCP socket (`socket://IP:8888`). Core OctoPrint does not list network serial ports by itself, so install a small plugin (recommended) or create a local pseudo-serial port with `socat`.

### Option A — Remote Connection plugin (recommended)

1. In OctoPrint, open **Settings → Plugin Manager → Get More**.
2. Install [OctoPrint-Remote_connection](https://plugins.octoprint.org/plugins/remote_connection/) from
   `https://github.com/mstarostik/OctoPrint-Remote_connection/archive/main.zip`
3. Restart OctoPrint.
4. Open **Settings → Remote Connection** (or the plugin’s settings page).
5. Add a device:
   - Host: Pico IP (`192.168.1.50`) or hostname (`pico-octoprint.local`)
   - Port: `8888`
   - Type: **raw** TCP (not RFC2217)
6. Save. On the OctoPrint home page, open the **Connection** panel.
7. Choose the new remote port.
8. Set **Baudrate** to the same value as `UART_BAUD` in `config.py` (the Pico sets the real UART speed; OctoPrint still wants a baud selected).
9. Click **Connect**.

The Pico LED should go solid. OctoPrint should show the printer as **Operational** after the firmware hello (`start` / `M115`).

Enable **Auto-connect on startup** in **Settings → Serial Connection** once a test print works.

### Option B — Network Printing plugin

1. Install [OctoPrint-Network-Printing](https://github.com/hellerbarde/OctoPrint-Network-Printing) from
   `https://github.com/hellerbarde/OctoPrint-Network-Printing/archive/main.zip`
2. Restart OctoPrint.
3. Open **Settings → Serial Connection → General → Additional serial ports**.
4. Add one of:

   ```
   socket://192.168.1.50:8888
   socket://pico-octoprint.local:8888
   ```

5. Save, reload the port list, select that port, set baud, and **Connect**.

### Option C — `socat` on the OctoPrint host

If you would rather give OctoPrint a normal device node:

```bash
sudo apt-get install socat
sudo socat PTY,link=/dev/ttyPICO,raw,echo=0,mode=666 TCP:192.168.1.50:8888
```

Then choose `/dev/ttyPICO` in the OctoPrint Connection panel. Use a systemd unit if you want this to survive reboot.

## 5. Confirm the link

1. Pico LED is solid.
2. OctoPrint Connection state is **Operational**.
3. **Terminal** tab: `M115` returns firmware info.
4. Temperature readout updates.
5. Run a small test print before trusting a long job. Wi-Fi dropouts will pause or fail the print; a wired USB connection is still more reliable than any serial-over-Wi-Fi path.

## Safe mode and recovery

- Hold **GP15 to GND**, tap RESET (or replug USB): `main.py` skips the bridge and leaves you in the REPL so you can edit `config.py`.
- Hold **BOOTSEL** while plugging in USB to reflash MicroPython. The on-device files usually remain; delete `main.py` from Thonny if the board will not stay in the REPL.
- After the watchdog starts, **Ctrl-C** in the REPL will reboot the Pico a few seconds later. That is expected.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Never joins Wi-Fi | 2.4 GHz SSID/password; Pico W cannot use 5 GHz. Open the USB console for status codes. |
| OctoPrint cannot connect | Same subnet, no AP isolation, correct IP/port, plugin installed, Pico LED slow-blinking (waiting) not fast-blinking (Wi-Fi). |
| Connects then garbage / no hello | TX/RX swapped, wrong baud, 5 V vs 3.3 V, try `UART_INVERT = True`. Unplug a second USB serial session to the printer. |
| Connects then stalls mid-print | Weak Wi-Fi; move the Pico closer to the AP. This firmware already disables CYW43 power save to cut latency. |
| `pico-octoprint.local` does not resolve | Use the IP from the USB log, or set `STATIC_IP`. |
| Thonny cannot open the Pico | Data-capable USB cable; another program has the serial port. Safe-mode GP15 if `main.py` is wedged. |

## Files

| File | Purpose |
| --- | --- |
| `src/main.py` | Bridge firmware (copy to Pico as `main.py`) |
| `src/config.example.py` | Settings template (copy to `config.py`, then to the Pico) |
