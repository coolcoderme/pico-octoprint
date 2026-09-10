"""Transparent UART-to-Wi-Fi serial bridge for Raspberry Pi Pico W.

The Pico W joins Wi-Fi, listens on a TCP port, and copies bytes in both
directions between that socket and a hardware UART. OctoPrint treats the
TCP port as a remote serial printer connection (raw socket / ESP3D-style).

USB CDC stays on the MicroPython REPL so you can configure the board with
Thonny or mpremote. Ground GP15 at reset to skip the bridge (safe mode).
"""

import time

try:
    import errno
except ImportError:
    errno = None

import network
import select
import socket
from machine import UART, Pin, WDT

try:
    from machine import idle
except ImportError:
    def idle():
        time.sleep_ms(0)

try:
    import config
except ImportError:
    print("Missing config.py. Copy config.example.py to config.py and set WIFI_SSID / WIFI_PASSWORD.")
    raise SystemExit

_WOULD_BLOCK = (11,)
if errno is not None:
    _WOULD_BLOCK = tuple(
        {
            getattr(errno, name)
            for name in ("EAGAIN", "EWOULDBLOCK")
            if getattr(errno, name, None) is not None
        }
    ) or _WOULD_BLOCK

POLLIN = getattr(select, "POLLIN", 1)
POLLHUP = getattr(select, "POLLHUP", 0x10)
POLLERR = getattr(select, "POLLERR", 0x08)

LED_CONNECTING_MS = 200
LED_WAITING_MS = 1000
POLL_MS = 1
SEND_TIMEOUT_MS = 2000
WIFI_RETRY_MS = 8000
STATUS_LOG_MS = 15000
RX_CHUNK = 512
UART_BUF = 4096
TCP_NODELAY = 1
CYW43_PM_PERFORMANCE = 0xA11140


def _cfg(name, default=None):
    return getattr(config, name, default)


def log(*parts):
    print(*parts)


def is_safe_mode():
    pin_no = _cfg("SAFE_MODE_PIN", 15)
    pin = Pin(pin_no, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(20)
    return pin.value() == 0


class StatusLED:
    def __init__(self):
        try:
            self._pin = Pin("LED", Pin.OUT)
        except (TypeError, ValueError):
            self._pin = Pin(25, Pin.OUT)
        self._on = False
        self._interval = LED_CONNECTING_MS
        self._last = time.ticks_ms()
        self.connected = False

    def set_waiting(self):
        self.connected = False
        self._interval = LED_WAITING_MS

    def set_connecting(self):
        self.connected = False
        self._interval = LED_CONNECTING_MS

    def set_client(self):
        self.connected = True
        self._pin.value(1)
        self._on = True

    def tick(self):
        if self.connected:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last) >= self._interval:
            self._on = not self._on
            self._pin.value(1 if self._on else 0)
            self._last = now


def send_all(sock, data, wdt=None):
    """Write every byte. Never drop serial payload; time out instead."""
    if not data:
        return
    view = memoryview(data)
    start = time.ticks_ms()
    while view:
        try:
            n = sock.send(view)
            if n:
                view = view[n:]
                continue
        except OSError as exc:
            err = exc.args[0] if exc.args else None
            if err not in _WOULD_BLOCK:
                raise
        if time.ticks_diff(time.ticks_ms(), start) > SEND_TIMEOUT_MS:
            raise OSError("tcp send timeout")
        if wdt:
            wdt.feed()
        idle()


def uart_write_all(uart, data, wdt=None):
    if not data:
        return
    view = memoryview(data)
    start = time.ticks_ms()
    while view:
        n = uart.write(view)
        if n:
            view = view[n:]
            continue
        if time.ticks_diff(time.ticks_ms(), start) > SEND_TIMEOUT_MS:
            raise OSError("uart send timeout")
        if wdt:
            wdt.feed()
        idle()


def wifi_configured():
    ssid = _cfg("WIFI_SSID", "")
    password = _cfg("WIFI_PASSWORD", "")
    if not ssid or ssid == "your-wifi-name":
        return False
    if password == "your-wifi-password":
        return False
    return True


def connect_wifi(led, wdt=None):
    ssid = _cfg("WIFI_SSID", "")
    password = _cfg("WIFI_PASSWORD", "")
    hostname = _cfg("WIFI_HOSTNAME", "pico-octoprint")
    static_ip = _cfg("STATIC_IP")

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(hostname=hostname)
    except (TypeError, ValueError, OSError):
        try:
            network.hostname(hostname)
        except (AttributeError, OSError):
            pass
    try:
        wlan.config(pm=CYW43_PM_PERFORMANCE)
    except (TypeError, ValueError, OSError):
        pass

    if static_ip:
        wlan.ifconfig(static_ip)

    led.set_connecting()
    log("Wi-Fi: connecting to", ssid)

    while True:
        if not wlan.isconnected():
            try:
                wlan.connect(ssid, password)
            except OSError as exc:
                log("Wi-Fi connect error:", exc)
            deadline = time.ticks_add(time.ticks_ms(), WIFI_RETRY_MS)
            while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
                led.tick()
                if wdt:
                    wdt.feed()
                time.sleep_ms(50)
        if wlan.isconnected():
            ip, netmask, gateway, dns = wlan.ifconfig()
            log("Wi-Fi: connected")
            log("  IP     ", ip)
            log("  mask   ", netmask)
            log("  gateway", gateway)
            log("  dns    ", dns)
            log("  host   ", hostname)
            return wlan, ip
        log("Wi-Fi: still not connected, retrying (status=%s)" % (wlan.status(),))
        try:
            wlan.disconnect()
        except OSError:
            pass
        time.sleep_ms(1000)


def make_uart():
    kwargs = dict(
        baudrate=int(_cfg("UART_BAUD", 115200)),
        bits=int(_cfg("UART_BITS", 8)),
        parity=_cfg("UART_PARITY", None),
        stop=int(_cfg("UART_STOP", 1)),
        tx=Pin(int(_cfg("UART_TX_PIN", 4))),
        rx=Pin(int(_cfg("UART_RX_PIN", 5))),
        txbuf=UART_BUF,
        rxbuf=UART_BUF,
        timeout=0,
        timeout_char=0,
    )
    if _cfg("UART_INVERT", False):
        if hasattr(UART, "INV_TX"):
            kwargs["invert"] = UART.INV_TX | UART.INV_RX
        else:
            log("UART_INVERT requested but this firmware has no UART invert support")
    uart = UART(int(_cfg("UART_ID", 1)), **kwargs)
    log(
        "UART: uart%s GP%s TX / GP%s RX @ %s 8N1"
        % (
            _cfg("UART_ID", 1),
            _cfg("UART_TX_PIN", 4),
            _cfg("UART_RX_PIN", 5),
            _cfg("UART_BAUD", 115200),
        )
    )
    return uart


def make_server(ip):
    port = int(_cfg("TCP_PORT", 8888))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(1)
    server.setblocking(False)
    log("TCP: listening on %s:%s (raw serial)" % (ip, port))
    log("OctoPrint: socket://%s:%s" % (ip, port))
    return server, port


def tune_client(client):
    client.setblocking(False)
    try:
        client.setsockopt(socket.IPPROTO_TCP, TCP_NODELAY, 1)
    except (AttributeError, OSError):
        pass
    try:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except (AttributeError, OSError):
        pass


def close_quietly(sock):
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


class Bridge:
    def __init__(self, uart, server, led, wdt, ip, port):
        self.uart = uart
        self.server = server
        self.led = led
        self.wdt = wdt
        self.ip = ip
        self.port = port
        self.client = None
        self.client_addr = None
        self.poller = select.poll()
        self.poller.register(self.uart, POLLIN)
        self.poller.register(self.server, POLLIN)
        self._wlan = network.WLAN(network.STA_IF)
        self._last_wifi_check = time.ticks_ms()
        self._last_status = time.ticks_ms()

    def drop_client(self, reason=""):
        if self.client is None:
            return
        if reason:
            log("TCP: disconnect %s (%s)" % (self.client_addr, reason))
        else:
            log("TCP: disconnect", self.client_addr)
        try:
            self.poller.unregister(self.client)
        except (OSError, KeyError, ValueError):
            pass
        close_quietly(self.client)
        self.client = None
        self.client_addr = None
        self.led.set_waiting()

    def accept_client(self):
        try:
            client, addr = self.server.accept()
        except OSError as exc:
            err = exc.args[0] if exc.args else None
            if err in _WOULD_BLOCK:
                return
            raise
        if self.client is not None:
            log("TCP: replacing", self.client_addr, "with", addr)
            self.drop_client("replaced")
        tune_client(client)
        self.client = client
        self.client_addr = addr
        self.poller.register(self.client, POLLIN | POLLHUP | POLLERR)
        self.led.set_client()
        log("TCP: OctoPrint connected from %s:%s" % (addr[0], addr[1]))

    def from_uart(self):
        data = self.uart.read(RX_CHUNK)
        if not data:
            return
        if self.client is None:
            return
        try:
            send_all(self.client, data, self.wdt)
        except OSError as exc:
            self.drop_client(str(exc))

    def from_tcp(self):
        if self.client is None:
            return
        try:
            data = self.client.recv(RX_CHUNK)
        except OSError as exc:
            err = exc.args[0] if exc.args else None
            if err in _WOULD_BLOCK:
                return
            self.drop_client(str(exc))
            return
        if not data:
            self.drop_client("peer closed")
            return
        try:
            uart_write_all(self.uart, data, self.wdt)
        except OSError as exc:
            log("UART write failed:", exc)

    def maybe_log_status(self):
        if self.client is not None:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_status) < STATUS_LOG_MS:
            return
        self._last_status = now
        log("Waiting for OctoPrint on socket://%s:%s" % (self.ip, self.port))

    def run(self):
        self.led.set_waiting()
        log("Bridge ready. USB REPL is still available for logs.")
        while True:
            self.wdt.feed()
            self.led.tick()
            if not self.wifi_still_up():
                raise OSError("wifi lost")
            self.maybe_log_status()
            events = self.poller.poll(POLL_MS)
            if not events:
                if self.uart.any() and self.client is not None:
                    self.from_uart()
                continue
            for obj, event in events:
                if obj is self.server:
                    self.accept_client()
                elif obj is self.uart:
                    self.from_uart()
                elif obj is self.client:
                    if event & (POLLHUP | POLLERR):
                        self.drop_client("poll error")
                    else:
                        self.from_tcp()

    def wifi_still_up(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_wifi_check) < 2000:
            return True
        self._last_wifi_check = now
        if self._wlan.isconnected():
            return True
        log("Wi-Fi: association lost")
        self.drop_client("wifi lost")
        return False


def main():
    log("pico-octoprint UART-to-Wi-Fi bridge")
    if is_safe_mode():
        log("Safe mode: GP%s is grounded. Bridge not started." % _cfg("SAFE_MODE_PIN", 15))
        return
    if not wifi_configured():
        log("Set WIFI_SSID and WIFI_PASSWORD in config.py, then reset the Pico W.")
        return

    led = StatusLED()
    led.set_connecting()
    wdt = WDT(timeout=8000)

    while True:
        try:
            uart = None
            server = None
            _wlan, ip = connect_wifi(led, wdt)
            uart = make_uart()
            server, port = make_server(ip)
            Bridge(uart, server, led, wdt, ip, port).run()
        except KeyboardInterrupt:
            log("Interrupted; watchdog will reset the Pico W")
            raise
        except Exception as exc:
            log("Bridge error:", exc)
            led.set_connecting()
            time.sleep_ms(2000)
        finally:
            close_quietly(server)
            if uart is not None:
                try:
                    uart.deinit()
                except OSError:
                    pass


main()
