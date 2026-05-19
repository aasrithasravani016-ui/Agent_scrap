# Test queries

Copy any line into the CLI (`python3 cli.py "<query>"`), the Streamlit **Ask**
tab, or run them all at once with `python3 run_tests.py`.

All models below are really in the database (54 models, 10 vendors), so they
should return a spec sheet. The "Not in KB" section should return the honest
*not-found → web-fallback* message.

## Spec lookup — by exact model

```
Arista 7060CX-32S
Cisco Nexus 9336C-FX2
Cisco Catalyst 9300-48P
Dell S5232F-ON
HPE Aruba 8325-48Y8C
Juniper QFX5120-48Y
NVIDIA SN4700
Netgear M4500-32C
TP-Link TL-SG3428
Ubiquiti USW-Pro-48
MikroTik CRS354-48G-4S+2Q+RM
```

## Spec lookup — vendor aliases & loose typing

```
mellanox SN5600          # mellanox -> NVIDIA
aruba 6300M-48G-PoE4+    # aruba -> HPE Aruba
jnpr EX4400-48P          # jnpr -> Juniper
arista 7050              # partial -> resolves to a 7050 model
9336C-FX2                # bare SKU, no vendor
catalyst 9500            # family + number
```

## Comparison

```
compare Cisco Catalyst 9300-48P vs Juniper EX4400-48P
compare Arista 7060CX-32S vs NVIDIA SN4700
SN5600 vs Nexus 9364D-GX2A
compare Dell S5232F-ON and Cisco Nexus 9336C-FX2
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
```

## Catalog

```
vendors
```

## Not in KB (should say "not found → web-fallback", NOT a wrong guess)

```
Cisco Catalyst 3850-48T
Arista 7170-64C
Juniper QFX10008
Some Made Up Switch 9999
```
