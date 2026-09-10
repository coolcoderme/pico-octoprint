# Copy this file to config.py on the Pico W and fill in your network.
#   cp config.example.py config.py
#
# config.py is gitignored so Wi-Fi credentials are not committed.

# 2.4 GHz Wi-Fi only. Pico W does not support 5 GHz networks.
WIFI_SSID = "your-wifi-name"
WIFI_PASSWORD = "your-wifi-password"

# mDNS / DHCP hostname. OctoPrint can use pico-octoprint.local if your
# network resolves it; otherwise use the IP printed on the USB serial console.
WIFI_HOSTNAME = "pico-octoprint"

# Optional static IPv4. Leave as None to use DHCP.
# STATIC_IP = ("192.168.1.50", "255.255.255.0", "192.168.1.1", "8.8.8.8")
STATIC_IP = None

# Raw TCP serial port. OctoPrint connects here (socket://<ip>:8888).
TCP_PORT = 8888

# UART1 on GP4 (TX) / GP5 (RX) is free on Pico W (wireless uses other pins).
UART_ID = 1
UART_TX_PIN = 4
UART_RX_PIN = 5
UART_BAUD = 115200
UART_BITS = 8
UART_PARITY = None
UART_STOP = 1

# Set True if the printer serial lines are inverted (some Creality TFT headers).
UART_INVERT = False

# Hold GP15 to GND while resetting to stay in the USB REPL (skip the bridge).
SAFE_MODE_PIN = 15
