# Test queries

Copy any line into the CLI (`python3 cli.py "<query>"`), the Streamlit **Ask**
tab, or run them all at once with `python3 run_tests.py`.

The database currently holds **240 models across 15 vendors**. Every model
listed below is really in the DB, so it should return a spec sheet. Lines
marked **🖼** have a product image backfilled, so they also exercise the
image rendering. The "Not in KB" section should return the honest
*not-found → web-fallback* message.

## Spec lookup — by exact model (all 15 vendors)

```
Arista 7060CX-32S
Arista 7280CR3-32D4
Cisco Catalyst 9300-48P            # 🖼
Cisco Catalyst 9200L-24P-4G        # 🖼
Cisco Nexus 9364D-GX2A             # 🖼
Dell S5232F-ON
Dell S4148F-ON
Edge-Core AS7726-32X
Extreme Networks 5320-48P-8XE
Fortinet FortiSwitch-448E-FPOE     # 🖼
HPE Aruba 8325-48Y8C
HPE Aruba 6300M-48G-PoE4+
Huawei CloudEngine S6730-H48X6C    # 🖼
Juniper EX4400-48P
Juniper EX4650-48Y
MikroTik CRS354-48G-4S+2Q+RM
MikroTik CRS305-1G-4S+IN           # 🖼
NVIDIA SN4700
NVIDIA SN5600
Netgear GS108MX                    # 🖼
Netgear CSM4316                    # 🖼
TP-Link TL-SG3428
TP-Link FESTA-FS328G               # 🖼
Ubiquiti USW-Pro-48                # 🖼
Ubiquiti USW-Enterprise-24-PoE     # 🖼
Zyxel XGS2220-30
```

## Spec lookup — vendor aliases & loose typing

```
mellanox SN5600          # mellanox -> NVIDIA
aruba 6300M-48G-PoE4+    # aruba -> HPE Aruba
jnpr EX4400-48P          # jnpr -> Juniper
arista 7050              # partial -> resolves to a 7050 model
arista 7280              # partial -> resolves to a 7280 model
9336C-FX2                # bare SKU, no vendor
C9300-48P                # bare Cisco SKU
catalyst 9500            # family + number
ex4400                   # lowercase, no vendor
```

## Comparison

```
compare Cisco Catalyst 9300-48P vs Juniper EX4400-48P
compare Arista 7060CX-32S vs NVIDIA SN4700
SN5600 vs Nexus 9364D-GX2A
compare Dell S5232F-ON and Cisco Nexus 9336C-FX2
compare HPE Aruba 8325-48Y8C vs Juniper EX4650-48Y
compare Ubiquiti USW-Pro-48 vs MikroTik CRS354-48G-4S+2Q+RM
```

## Spec filters

```
which switches support 400G
which switches support 100G
switches with PoE over 600W
spine switches
leaf switches
which switches have EVPN-VXLAN
which switches support MACsec
list layer 3 switches
Cisco switches with PoE
24-port switches
```

## Catalog

```
vendors
```

## Firmware advisor (Streamlit "Firmware advisor" tab — model + version)

The local `firmware_versions` table is empty, so this exercises the **live
fetch** path. MikroTik has the best public coverage; others may return the
honest "no public firmware data" message with a vendor-portal link.

```
Model: MikroTik CRS326-24G-2S+RM     Version: 7.10.2
Model: MikroTik CRS354-48G-4S+2Q+RM  Version: 7.8
Model: Cisco Catalyst 9300-48P       Version: 17.6.1
Model: Juniper EX4400-48P            Version: 21.4R1
```

## Not in KB (should say "not found → web-fallback", NOT a wrong guess)

```
Cisco Catalyst 3850-48T
Arista 7170-64C
Juniper QFX10008
Some Made Up Switch 9999
```
