# pyskinny — dusty-but-useful (maybe) CallManager tooling for Python

> Have you ever needed to use the SCCP (Skinny) protocol in your Python project? **Probably not.**  
> Looking for automation tools for **legacy Cisco CallManager**? **Doubtful.**  
> Didn’t IP Telephony die like 10 years ago? **Allegedly.**  
> But *on the off chance* you’re here for exactly that… **you’ve come to the right place.**

pyskinny includes both a SCCP Client and a grab-bag of practical scripts for poking at **old-school CUCM/CallManager (4.x)**: AXL v1 SOAP, SQL via AXL, real-time snapshots via the RTMT **ASTIsapi** endpoints, and direct **79xx phone control** (screenshots + button presses).

---

## What’s inside

- **SCCP 'Softphone' Client**
  - Macro Mode
  - Cisco-esque CLI mode
- **CallManager 4.1 AXL v1 SOAP helpers**
  - `listPhoneByName` / `listPhoneByDescription`
  - `executeSQLQuery` with a **smart rewrite** to safely expand `Device.*` (avoids the XML LOB column)
- **AST / “RIS-ish” device snapshot**
  - Uses `ASTIsapi.dll?OpenDeviceSearch` (works on 4.x; TLSv1 & NTLM friendly)
- **Phone control (79xx era)**
  - `/CGI/Screenshot` (decodes CiscoIPPhoneImage → PNG)
  - `/CGI/Execute` (dial digits, softkeys, navigation, hardkeys)
- **JSON everywhere**
  - `--json`, `--jsonl`, `--pretty`

---

## Requirements
- Python **3.11+** (tested on 3.12)
- macOS/Linux (Windows likely fine)
- System **curl** (for ancient TLS fallbacks)
- Python deps (example):
  ```bash
  pip install -r requirements.txt
  ```
- Note: Tested only with CallManager 4.1(3). Will it work on other versions? **Unlikely.**

---

## Quick start

Clone your repo and set up a venv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### examples/run_macro.py
#### Macro-mode CLI SCCP Client
```bash
# Using a macro file
python -m examples.run_macro --server <server_ip_or_hostname> --mac <device_mac_address> --model <device_model_number> --macro-file examples/ivr.macro
2025-09-05 11:35:13,643 [MESSAGE] ui.macro_cli          : Executing: ON_DISCONNECT ['GOTO', 'TOP']
2025-09-05 11:35:13,643 [MESSAGE] ui.macro_cli          : Executing: WAIT_CALL ['0', 'RING']
2025-09-05 11:35:13,643 [MESSAGE] ui.macro_cli          : Press 'q' to quit
2025-09-05 11:35:25,031 [MESSAGE] ui.macro_cli          : Executing: SOFTKEY ['Answer']
2025-09-05 11:35:25,534 [MESSAGE] ui.macro_cli          : Executing: GOTO ['MENU']
2025-09-05 11:35:25,534 [MESSAGE] ui.macro_cli          : Executing: PLAY ['media/main_menu.wav']
2025-09-05 11:35:25,542 [MESSAGE] ui.macro_cli          : Executing: WAIT_DIGIT ['0']
2025-09-05 11:35:34,450 [MESSAGE] ui.macro_cli          : Executing: SWITCH ['last_digit', '1:SERVICE;2:SUPPORT;3:EXT_DIAL;9:MENU;DEFAULT:MENU']
2025-09-05 11:35:34,450 [MESSAGE] ui.macro_cli          : Executing: PLAY ['media/customer_service.wav']
2025-09-05 11:35:34,454 [MESSAGE] ui.macro_cli          : Executing: WAIT_DIGIT ['0']
2025-09-05 11:35:45,351 [MESSAGE] ui.macro_cli          : Executing: WAIT_CALL ['0', 'RING']
2025-09-05 11:35:45,351 [MESSAGE] ui.macro_cli          : Press 'q' to quit

# Using a macro from the CLI
python -m examples.run_macro -vvvv --server <server_ip_or_hostname> --mac <device_mac_address> --model <device_model_number> --macro "WAIT 2,CALL 1001,WAIT 10,SOFTKEY EndCall"
2025-09-05 11:37:38,817 [MESSAGE] ui.macro_cli          : Executing: WAIT ['2']
2025-09-05 11:37:40,822 [MESSAGE] ui.macro_cli          : Executing: CALL ['1001']
2025-09-05 11:37:43,344 [MESSAGE] ui.macro_cli          : Executing: WAIT ['10']
2025-09-05 11:37:53,349 [MESSAGE] ui.macro_cli          : Executing: SOFTKEY ['EndCall']
```

### examples/run_cli.py
#### Cisco-esque CLI SCCP Client
```bash
python -m examples.run_cli
Press '?' for help. Type 'exit' to quit.
phone# set server 10.0.0.180
server = 10.0.0.180

phone# set mac 222233334444
mac = 222233334444

phone# set model 7970
model = 7970

phone# set auto_connect true
auto_connect = True

phone# save
phone# show config
server: 10.0.0.180
mac:    222233334444
model:  7970
auto_connect: True

phone# connect
phone# phone call 1006
Calling 1006 ...

phone# show call
Line   CallId    CallType      CallState      Time        FromNum      FromName        ToNum        ToName         
1      16777221  OutBoundCall  Connected      2 seconds   1003         Python          1006         Python7971     

phone# phone send softkey EndCall
Softkey EndCall (line 1, call 0)

phone# exit
```

### tools/callmanager.py
#### List phones via AXL

```bash
python tools/callmanager.py --server <server_ip_or_hostname> --user administrator --pass <windows_admin_password> --mode name --pattern 'SEP%' --json --pretty
[
    {
        "pkid": "b4fa8ba2-ccc1-419b-9c3b-a447d0ab3604",
        "name": "SEP333344445555",
        "product": "Cisco 7971",
        "model": "Cisco 7971"
    }
]
```

#### Run SQL safely (auto-expands Device.*)

```bash
python tools/callmanager.py --server <server_ip_or_hostname> --user administrator --pass <windows_admin_password>   --sql "SELECT d.*, n.DNOrPattern
         FROM Device d
         JOIN DeviceNumPlanMap m ON m.fkDevice = d.pkid
         JOIN NumPlan n ON n.pkid = m.fkNumPlan
         ORDER BY d.Name" --pretty
[
  {
    "pkid": "{B4FA8BA2-CCC1-419B-9C3B-A447D0AB3604}",
    "Name": "SEP333344445555",
    "Description": "SEP333344445555",
    "tkModel": "119",
    "tkDeviceProtocol": "0",
    "tkProtocolSide": "1",
    "SpecialLoadInformation": "",
    "fkDevicePool": "{F71F52BC-B6C9-4968-8A86-DCDA3EEC3DD7}",
    "fkPhoneTemplate": "{9C9F4E1E-7879-4AD0-842F-A0F253864260}",
    "AssocPC": "",
    "fkCallingSearchSpace": "{96B5C16D-68B7-41FF-960F-36990DB223EC}",
    "CtiID": "1942436578",
    "tkClass": "1",
    "AddOnModules": "0",
    "fkProcessNode": "",
    "DefaultDTMFCapability": "0",
    "fkLocation": "{C8185284-D1D9-4FD5-9D7B-6ED6BB0F646C}",
    "tkProduct": "119",
    "DialPlanWizardGenID": "",
    "DeviceLevelTraceFlag": "0",
    "LoginUserid": "",
    "LoginTime": "",
    "AllowHotelingFlag": "0",
    "tkDeviceProfile": "0",
    "ikDevice_DefaultProfile": "",
    "fkMediaResourceList": "{B2E1E3C2-5198-47FC-9F44-B898CD542D2C}",
    "UserHoldMOHAudioSourceID": "0",
    "NetworkHoldMOHAudioSourceID": "0",
    "LoginDuration": "",
    "Unit": "0",
    "SubUnit": "0",
    "VersionStamp": "{1EF073B9-5898-4109-B1C7-96F4969B5A4C}",
    "tkCountry": "",
    "ikDevice_CurrentLoginProfile": "",
    "tkUserLocale": "",
    "tkProduct_Base": "",
    "fkCallingSearchSpace_AAR": "",
    "fkAARNeighborhood": "",
    "fkSoftkeyTemplate": "",
    "retryVideoCallAsAudio": "1",
    "RouteListEnabled": "",
    "fkCallManagerGroup": "",
    "tkStatus_MLPPIndicationStatus": "2",
    "tkPreemption": "2",
    "MLPPDomainID": "-1",
    "tkStatus_CallInfoPrivate": "2",
    "tkStatus_BuiltInBridge": "2",
    "tkQSIG": "4",
    "tkDeviceSecurityMode": "0",
    "V150ModemRelayCapable": "0",
    "tkNetworkLocation": "0",
    "ignorePI": "0",
    "tkPacketCaptureMode": "0",
    "PacketCaptureDuration": "60",
    "AuthenticationString": "",
    "tkAuthenticationMode": "1",
    "tkCertificateStatus": "1",
    "tkKeySize": "2",
    "tkCertificateOperation": "1",
    "UpgradeFinishTime": "",
    "tkCertificate": "0",
    "msrepl_tran_version": "{4895266D-F371-49FA-8818-12CAC83FE7C7}",
    "DNOrPattern": "1006"
  }
]
```

> Tip: `--no-rewrite` disables the safety net if you really want raw SQL.

#### Real-time “registered devices” snapshot (ASTIsapi)

```bash
python tools/callmanager.py --server 10.0.0.180   --user administrator --pass <windows_admin_password> --ris --pretty
{
  "node": "CUCM4",
  "totalDevices": 1,
  "devices": [
    {
      "name": "SEP333344445555",
      "ip": "192.168.100.195",
      "dirNumber": "1006",
      "status_enum": 2,
      "status": "Unregistered",
      "model_enum": 119,
      "model": "Cisco 7971",
      "product_enum": 119,
      "product": "Cisco 7971",
      "perfmonObject": 2,
      "timestamp_raw": "1757065587",
      "timestamp_iso": "2025-09-05T09:46:27Z"
    }
  ]
}
```

---

#### Argument summary

- General:
  - `--server <ip_or_hostname> --user administrator --pass <windows_admin_password>`
- AXL listing:
  - `--mode {name|description}` , `--pattern 'SEP%'`
- SQL:
  - `--sql "SELECT …"`, `--no-rewrite` (optional)
- AST/RIS-ish:
  - `--ris`
- Output:
  - `--json` (array), `--jsonl` (one object per line), `--pretty`

---

### tools/phone.py
### Phone screenshot + button presses (79xx)

```bash
# Screenshot (auto-detects CiscoIPPhoneImage, writes PNG)
python tools/phone.py --phoneip 10.0.0.71 --user <username> --pass <password> --output screenshot.png

# Dial a number
python tools/phone.py --phoneip 10.0.0.71 --user <username> --pass <password> --dial 1001

# Press keys/softkeys/navigation
python tools/phone.py --phoneip 10.0.0.71 --user <username> --pass <password> --keys "123#"
python tools/phone.py --phoneip 10.0.0.71 --user <username> --pass <password> --softkey 1
python tools/phone.py --phoneip 10.0.0.71 --user <username> --pass <password> --nav down
```

> Enable **Web Access = Enabled** on the phone in CUCM.  
> In order for auth to work, you'll need to associate a user to the device in CallManager, then you can authenticate with those user credentials.

---

### tools/cme.py
#### Read CallManager Express configuration and make JSON backup

```bash
# Extract voice related configuration parameters from CME and store in JSON file. Specify DN range to build database of used DNs.
python tools/cme.py --host <cme_ip_or_hostname> --username <router_username> --password <router_password> --transport telnet collect -o <filename.json> --dn-start 9000 --dn-end 9999
  
# Add a new phone to CME. Dry run will show you the configuration that will be added.
python tools/cme.py --host <cme_ip_or_hostname> --username <router_username> --password <router_password> --transport telnet add-phone --json <filename.json> --mac 4444.5555.6666 --model 7970 --dry-run

# Add a new phone to CME. Actually add the configuration and save it.
python tools/cme.py --host <cme_ip_or_hostname> --username <router_username> --password <router_password> --transport telnet add-phone --json <filename.json> --mac 4444.5555.6666 --model 7970 --commit
```

> Enable **Web Access = Enabled** on the phone in CUCM.  
> In order for auth to work, you'll need to associate a user to the device in CallManager, then you can authenticate with those user credentials.

---

## Compatibility notes

- Targeted at **CUCM/CallManager 4.x** (Windows/IIS).
- AXL WSDL: `/CCMAPI/AXL/V1/AXLAPI.wsdl`
- ASTIsapi: `/ast/ASTIsapi.dll` (`OpenDeviceSearch`, `GetAlertSummaryList`, etc.)
- Phone models tested: **7940/7960** (others likely work if they expose `/CGI/*`).

---

## Troubleshooting

- **“XML is a large text column…”**: don’t `SELECT * FROM Device`; the tool auto-expands safe columns or pick columns explicitly.
- **TLS/SSL errors (EOF / handshake)**: these boxes speak **TLS1.0 + antique ciphers**. The scripts fall back to:
  - forcing TLSv1 in `requests`, and if needed,
  - shelling out to `curl --tlsv1` (and `--ntlm`).
- **Unauthorized HTML instead of XML**: include the **domain** (`CUCM4\administrator`) for NTLM, and use the **double-?** URL.

---

## Roadmap / TODO / Ideas
- [ ] Add ability to answer calls (and implement auto-answer) to run_cli.py
- [ ] Try to add better call handling to run_cli.py (or to base SCCPClient). It's currently very difficult to manage multiple calls (i.e., place a call on hold and then dial a second number)
- [ ] CallManager simulator (lightweight CM server that phones can register to)
- [ ] SIP phone support
- [ ] Console based "GUI" SCCP Client
- [ ] Wrap into a small **package** (`pip install pyskinny`)
- [ ] Optional TUI/mini web UI for screenshots + actions

---

## Use responsibly

These endpoints are old and permissive. Keep usage to **trusted lab/LANs** and authorized systems. Don’t enable phone web access on exposed networks.

---

## License
MIT