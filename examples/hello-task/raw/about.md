# reproxy

reproxy is an offline-first resilient proxy agent for networks that are
broken, filtered, captive, or partially working. Where most tools assume
"the internet works," reproxy assumes it doesn't, and degrades honestly:
Normal → Degraded → EmergencyText → Captive → Offline.

It diagnoses the network first, then picks the best usable transport
from a ladder (Trojan-WS, REALITY, DNS-over-HTTPS, ICMP tunnel, ...).
When nothing works, it says so plainly rather than pretending.

The project's tagline: *Happy Eyeballs for proxy transports, with honest
degradation.*
