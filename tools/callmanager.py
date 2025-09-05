import requests, xml.etree.ElementTree as ET
import sys
import argparse
import json
import re
from datetime import datetime, UTC
import subprocess
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl
from requests_ntlm import HttpNtlmAuth
HAVE_NTLM=True


NS = "http://www.cisco.com/AXLAPIService/"
NS_AST  = "http://schemas.cisco.com/ast/soap"
SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
device_cols = ['pkid', 'Name', 'Description', 'tkModel', 'tkDeviceProtocol', 'tkProtocolSide', 'SpecialLoadInformation', 'fkDevicePool', 'fkPhoneTemplate', 'AssocPC', 'fkCallingSearchSpace', 'CtiID', 'tkClass', 'AddOnModules', 'fkProcessNode', 'DefaultDTMFCapability', 'fkLocation', 'tkProduct', 'DialPlanWizardGenID', 'DeviceLevelTraceFlag', 'LoginUserid', 'LoginTime', 'AllowHotelingFlag', 'tkDeviceProfile', 'ikDevice_DefaultProfile', 'fkMediaResourceList', 'UserHoldMOHAudioSourceID', 'NetworkHoldMOHAudioSourceID', 'LoginDuration', 'Unit', 'SubUnit', 'VersionStamp', 'tkCountry', 'ikDevice_CurrentLoginProfile', 'tkUserLocale', 'tkProduct_Base', 'fkCallingSearchSpace_AAR', 'fkAARNeighborhood', 'fkSoftkeyTemplate', 'retryVideoCallAsAudio', 'RouteListEnabled', 'fkCallManagerGroup', 'tkStatus_MLPPIndicationStatus', 'tkPreemption', 'MLPPDomainID', 'tkStatus_CallInfoPrivate', 'tkStatus_BuiltInBridge', 'tkQSIG', 'tkDeviceSecurityMode', 'V150ModemRelayCapable', 'tkNetworkLocation', 'ignorePI', 'tkPacketCaptureMode', 'PacketCaptureDuration', 'AuthenticationString', 'tkAuthenticationMode', 'tkCertificateStatus', 'tkKeySize', 'tkCertificateOperation', 'UpgradeFinishTime', 'tkCertificate', 'msrepl_tran_version']


def envelope(op: str, search: str) -> str:
    # v1 list operations want <searchString> inside the op element
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAPENV}" xmlns:axl="{NS}">
  <soapenv:Header/>
  <soapenv:Body>
    <axl:{op}>
      <searchString>{search}</searchString>
    </axl:{op}>
  </soapenv:Body>
</soapenv:Envelope>
"""


def axl_call(SOAP_URL, op: str, term: str, user: str, pwd: str):
    body = envelope(op, term)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": NS + op,  # IIS/ASMX expects this style on AXL v1
    }
    r = requests.post(SOAP_URL, headers=headers, data=body, auth=(user, pwd), timeout=20)
    r.raise_for_status()
    return r.text


def parse_phones(xml_text: str):
    root = ET.fromstring(xml_text)
    # Success case usually returns a list of <phone> elements; be permissive:
    # find any element with tag ending in 'phone' or direct children with <name>.
    phones = []
    for phone in root.iter():
        if phone.tag.endswith("phone"):
            d = {}

            # capture the UUID attribute (with or without a namespace)
            uuid = None
            for k, v in phone.attrib.items():
                if k.split('}', 1)[-1].lower() == "uuid":
                    uuid = v
                    break
            if uuid is not None:
                d["pkid"] = uuid.replace("{", "").replace("}", "").lower()

            for c in list(phone):
                tag = c.tag.split("}",1)[-1]
                d[tag] = (c.text or "").strip()
            if d:
                phones.append(d)
    # Fallback: some builds put rows under <row>
    if not phones:
        for row in root.findall(".//row"):
            d = {}
            for c in list(row):
                tag = c.tag.split("}",1)[-1]
                d[tag] = (c.text or "").strip()
            if d:
                phones.append(d)
    # Fault helper
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    return phones, fault


def items_to_xml(items):
    return "\n".join(f"<ast:item><ast:Item>{i}</ast:Item></ast:item>" for i in items)


def build_body(pattern, select_by="Name", device_class="Phone", status="Any", max_devices=2000):
    ENVELOPE_TPL = """<?xml version="1.0" encoding="utf-8"?>
    <soapenv:Envelope xmlns:soapenv="{soapenv}" xmlns:ast="{ast}">
      <soapenv:Header/>
      <soapenv:Body>
        <ast:selectCmDevice>
          <ast:StateInfo></ast:StateInfo>
          <ast:CmSelectionCriteria>
            <ast:MaxReturnedDevices>{max_devices}</ast:MaxReturnedDevices>
            <ast:DeviceClass>{device_class}</ast:DeviceClass>
            <ast:Model>255</ast:Model>
            <ast:Status>{status}</ast:Status>
            <ast:NodeName></ast:NodeName>
            <ast:SelectBy>{select_by}</ast:SelectBy>
            <ast:SelectItems>
              {items_xml}
            </ast:SelectItems>
            <ast:Protocol>Any</ast:Protocol>
            <ast:DownloadStatus>Any</ast:DownloadStatus>
          </ast:CmSelectionCriteria>
        </ast:selectCmDevice>
      </soapenv:Body>
    </soapenv:Envelope>"""

    return ENVELOPE_TPL.format(
        soapenv=SOAPENV, ast=NS,
        max_devices=max_devices, device_class=device_class, status=status,
        select_by=select_by, items_xml=items_to_xml([pattern])
    )


def axl_execute_sql(SOAP_URL, sql: str, user: str, pwd: str) -> str:
    # Use CDATA to be robust with symbols
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAPENV}" xmlns:axl="{NS}">
  <soapenv:Header/>
  <soapenv:Body>
    <axl:executeSQLQuery>
      <sql><![CDATA[{sql}]]></sql>
    </axl:executeSQLQuery>
  </soapenv:Body>
</soapenv:Envelope>"""
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": NS + "executeSQLQuery"}
    r = requests.post(SOAP_URL, headers=headers, data=body, auth=(user, pwd), timeout=20)
    r.raise_for_status()
    return r.text


def parse_sql_rows(xml_text: str):
    root = ET.fromstring(xml_text)
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fs = (fault.findtext("faultstring") or "").strip()
        raise RuntimeError(f"SOAP Fault: {fs}")
    rows = []
    for row in root.findall(".//row"):
        d = {}
        for c in list(row):
            tag = c.tag.split('}', 1)[-1]
            d[tag] = (c.text or "").strip()
        rows.append(d)
    return rows


# ---- Smart SQL rewrite to avoid LOBs from Device ----
DEV_PAT = r"(?:dbo\.)?Device"  # matches Device or dbo.Device (case-insensitive)

def _expand_cols(prefix: str) -> str:
    """Return a comma-joined list like 'd.[pkid], d.[Name], ...' or '[pkid], [Name], ...'."""
    if prefix:
        return ", ".join(f"{prefix}.[{c}]" for c in device_cols)
    return ", ".join(f"[{c}]" for c in device_cols)

def smart_rewrite_sql(sql: str) -> str:
    s = sql
    # 1) Find all aliases used with Device in FROM/JOIN
    alias_re = re.compile(rf"\b(?:from|join)\s+{DEV_PAT}\s+(?:as\s+)?([A-Za-z_]\w*)", re.I)
    aliases = set(m.group(1) for m in alias_re.finditer(s))

    # If Device appears without alias, track a pseudo-alias of "" for direct-qualified replacements
    device_mentioned = re.search(rf"\b(?:from|join)\s+{DEV_PAT}\b", s, re.I) is not None
    if device_mentioned:
        aliases.add("")  # "" means no alias; we'll handle Device.* below

    # 2) Replace explicit alias stars: d.*  -> d.[col1], d.[col2], ...
    for a in sorted([x for x in aliases if x], key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(a)}\s*\.\s*\*",
                   _expand_cols(a),
                   s, flags=re.I)

    # 3) Replace Device.* (or dbo.Device.*) when used explicitly
    s = re.sub(rf"\b{DEV_PAT}\s*\.\s*\*", _expand_cols("Device"), s, flags=re.I)

    # 4) If SELECT * and ONLY Device in FROM (no other base tables), expand the bare star
    #    Detect other tables in FROM/JOIN (exclude subqueries/derived tables)
    tbl_re = re.compile(r"\b(?:from|join)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)", re.I)
    tables = [m.group(1) for m in tbl_re.finditer(s)]
    other_tables = [t for t in tables if re.match(rf"^{DEV_PAT}$", t, re.I) is None]
    only_device = device_mentioned and len(other_tables) == 0

    # Is there a bare star in the SELECT list?
    # Try to limit replacement to before the first FROM.
    m_from = re.search(r"\bfrom\b", s, re.I)
    if only_device and m_from:
        head = s[:m_from.start()]
        tail = s[m_from.start():]
        head2 = re.sub(r"(?i)\bselect\s+(distinct\s+|top\s+\d+\s+)?\*",
                       lambda m: m.group(0).replace("*", _expand_cols("")),
                       head, count=1)
        s = head2 + tail

    return s


class LegacyTLSAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        # Build context BEFORE super().__init__ (requests may call init_poolmanager)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        # Force exactly TLSv1
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.maximum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        # Allow legacy ciphers (3DES, etc.)
        for spec in ("ALL:@SECLEVEL=0", "DEFAULT:@SECLEVEL=0"):
            try:
                ctx.set_ciphers(spec)
                break
            except Exception:
                continue
        # Help old servers
        try: ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        except Exception: pass
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self._ctx = ctx
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self._ctx
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _curl_open_device_search(url, user, pwd, use_ntlm=False, timeout=12):
    # Uses system curl to force TLSv1; returns text or raises
    cmd = [
        "curl", "-sS", "-k", "--tlsv1", "--connect-timeout", str(timeout),
        "-u", f"{user}:{pwd}",
        url
    ]
    if use_ntlm:
        cmd.insert(1, "--ntlm")

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"curl failed: {res.stderr.strip() or res.returncode}")
    txt = res.stdout
    if txt.strip().upper().startswith("BAD REQUEST"):
        # try POST form-encoded with curl
        cmd_post = cmd[:-1] + ["-X", "POST", url]
        res2 = subprocess.run(cmd_post, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res2.returncode != 0 or res2.stdout.strip().upper().startswith("BAD REQUEST"):
            raise RuntimeError(f"curl POST failed: {res2.stderr.strip() or res2.returncode}\n{res2.stdout[:200]}")
        txt = res2.stdout
    return txt


def _auths(user, pwd, ntlm_domain=None):
    """Yield auth methods to try: Basic, then NTLM (optional)."""
    yield (user, pwd)  # Basic
    if HAVE_NTLM:
        u = f"{ntlm_domain}\\{user}" if ntlm_domain else user
        yield HttpNtlmAuth(u, pwd)


def _try_int(x):
    try:
        return int(x) if x is not None else None
    except ValueError:
        return x


def _ts_to_iso(ts):
    try:
        dt = datetime.fromtimestamp(int(ts), UTC)           # tz-aware in UTC
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return None


def to_enum_name_map(rows, *, coerce_int=False):
    """
    Convert [{'Enum': '8', 'Name': 'Cisco 7940'}, ...] -> {'8': 'Cisco 7940'} (or {8: 'Cisco 7940'}).
    - coerce_int=True makes keys ints when possible.
    - Missing/None Enum/Name entries are skipped.
    - Later duplicates overwrite earlier ones.
    """
    out = {}
    for r in rows or []:
        k = r.get("Enum")
        v = r.get("Name")
        if k is None or v is None:
            continue
        if coerce_int:
            try:
                k = int(k)
            except (ValueError, TypeError):
                pass
        out[k] = v
    return out


def parse_devices(host, user, pwd, xml_text: str):
    BASE = f"http://{host}/CCMAPI/AXL/V1"
    SOAP_URL = f"{BASE}/SOAPISAPI.dll"

    root = ET.fromstring(xml_text)
    node = root.find("ReplyNode")
    if node is None:
        raise RuntimeError("Unexpected response:\n" + xml_text[:400])

    devices=[]
    status_values = {"1": "Registered", "2": "Unregistered"}
    models = to_enum_name_map(parse_sql_rows(axl_execute_sql(SOAP_URL, "SELECT Enum,Name FROM TypeModel", user, pwd)))
    products = to_enum_name_map(parse_sql_rows(axl_execute_sql(SOAP_URL, "SELECT Enum,Name FROM TypeProduct", user, pwd)))
    # print(models)
    # print(products)

    for dev in node.findall("Device"):
        a = dev.attrib
        devices.append({
            "name": a.get("Name"),
            "ip": a.get("IpAddress"),
            "dirNumber": a.get("DirNumber"),
            "status_enum": int(a["Status"]) if a.get("Status") else None,
            "status": status_values.get(a["Status"]),
            "model_enum": int(a["Model"]) if a.get("Model") else None,
            "model": models.get(a["Model"]),
            "product_enum": int(a["Product"]) if a.get("Product") else None,
            "product": products.get(a["Product"]),
            "perfmonObject": int(a["PerfMonObject"]) if a.get("PerfMonObject") else None,
            "timestamp_raw": a.get("TimeStamp"),
            "timestamp_iso": _ts_to_iso(a.get("TimeStamp")),
        })
    return {
        "node": node.attrib.get("Name"),
        "totalDevices": int(root.attrib.get("TotalDevices","0")),
        "devices": devices,
    }


def open_device_search(host, user, pwd, pattern="SEP*", status="Any", max_devices=200,
                       select_by="Name", device_type="", ntlm_domain=None, timeout=12):
    # Keep '*' literal
    qs = (
        f"Type={device_type}&NodeName=&SubSystemType=&Status={status}"
        f"&MaxDevices={max_devices}&Model=&SearchType={select_by}"
        f"&SearchPattern={pattern}"                                         #SelectBy={select_by}&Protocol=Any&
    )
    urls = [
        f"https://{host}/ast/ASTIsapi.dll?OpenDeviceSearch&{qs}",
    ]

    # print(qs)
    # First try with requests using our TLSv1 adapter
    # s = requests.Session()
    # s.headers.update({"Connection":"close"})
    # s.mount("https://", LegacyTLSAdapter())
    # last_err = None
    # for url in urls:
    #     # for auth in _auths(user, pwd, ntlm_domain):
    #     if True:
    #         auth = (user, pwd)
    #         try:
    #             r = s.get(url, auth=auth, timeout=timeout, verify=False)
    #             if r.status_code == 401:
    #                 continue
    #             r.raise_for_status()
    #             txt = r.text
    #             if txt.strip().upper().startswith("BAD REQUEST"):
    #                 r = s.post(url, data={}, auth=auth, timeout=timeout, verify=False)
    #                 if r.status_code == 401:
    #                     continue
    #                 r.raise_for_status()
    #                 txt = r.text
    #                 if txt.strip().upper().startswith("BAD REQUEST"):
    #                     raise RuntimeError("Server returned BAD REQUEST")
    #             return parse_devices(txt)
    #         except Exception as e:
    #             last_err = e
    #             continue

    # Fallback: system curl with --tlsv1 (Basic first, then NTLM)
    for url in urls:
        try:
            txt = _curl_open_device_search(url, user, pwd, use_ntlm=False, timeout=timeout)
            return parse_devices(host, user, pwd, txt)
        except Exception as e:
            last_err = e
        # if HAVE_NTLM:
        #     try:
        #         txt = _curl_open_device_search(url, user, pwd, use_ntlm=True, timeout=timeout)
        #         return parse_devices(txt)
        #     except Exception as e:
        #         last_err = e

    # raise RuntimeError(f"OpenDeviceSearch failed (TLSv1 + curl fallback): {last_err}")


def main():
    ap = argparse.ArgumentParser(description="AXL v1 phone lister")
    ap.add_argument("--server", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="pwd", required=True)
    ap.add_argument("--mode", choices=["name","description"], default="name")
    ap.add_argument("--pattern", default="%")
    ap.add_argument("--sql", help='Run a raw SQL statement (wrap in double quotes). Example: --sql "SELECT TOP 5 name FROM Device"')
    ap.add_argument("--ris", action="store_true", help='Execute a RIS query against one or more devices"')
    ap.add_argument("--no-rewrite", action="store_true", help="Disable smart rewrite (Device.* or SELECT * FROM Device stays as-is)")
    # JSON output controls
    ap.add_argument("--json", action="store_true", help="Emit a JSON array to stdout")
    ap.add_argument("--jsonl", action="store_true", help="Emit JSON Lines (one object per line)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON (indent=2)")

    args = ap.parse_args()


    def emit(obj):
        """Emit JSON according to flags; silence any extra text."""
        indent = 2 if args.pretty else None
        if args.jsonl and isinstance(obj, list):
            out = "\n".join(json.dumps(x, ensure_ascii=False, default=str) for x in obj)
        else:
            out = json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
        # if args.output:
        #     with open(args.output, "w", encoding="utf-8") as f:
        #         f.write(out)
        # else:
        print(out)

    BASE = f"http://{args.server}/CCMAPI/AXL/V1"
    SOAP_URL = f"{BASE}/SOAPISAPI.dll"

    if args.sql:
        sql = args.sql if args.no_rewrite else smart_rewrite_sql(args.sql)
        xml = axl_execute_sql(SOAP_URL, sql, args.user, args.pwd)
        rows = parse_sql_rows(xml)
        if args.json or args.jsonl or args.pretty:      #or args.output
            emit(rows)
        else:
            # default to JSON if not specified (you asked for raw JSON)
            emit(rows)
    elif args.ris:
        data = open_device_search(args.server, args.user, args.pwd,
                                  pattern="SEP*", status="Any",
                                  max_devices=200, select_by="Name")
        print(json.dumps(data, indent=2 if args.pretty else None))
        # body = build_body(args.pattern, args.select_by, args.device_class, args.status, args.max)
        # body = build_body("SEP*", "Name", "Phone", "Any", "50")
        # xml, hit_url = ris_call(RIS_URL, args.user, args.pwd, body, verify_ssl=False)
        # print(hit_url)
        # print(xml)

        # body = body_v4_flat("SEP*", "Name", "Phone", "Any", "50"),
        # action = "http://schemas.cisco.com/ast/soap/action/#AST#SelectCmDevice"
        # xml = try_post(RIS_URL, body[0], action, args.user, args.pwd)

    else:
        op = "listPhoneByName" if args.mode == "name" else "listPhoneByDescription"
        xml = axl_call(SOAP_URL, op, args.pattern, args.user, args.pwd)
        phones, fault = parse_phones(xml)

        if fault is not None:
            code = fault.findtext("faultcode") or ""
            msg  = (fault.findtext("faultstring") or "").strip()
            print(f"SOAP Fault: {code} - {msg}")
            print(xml[:1200])
            sys.exit(2)

        if not phones:
            print("(no phones matched)")
            return

        print(json.dumps(phones, indent=4))


if __name__ == "__main__":
    main()


# select_device_sql = "SELECT " + ",".join(f"{c}" for c in device_cols) + " FROM Device ORDER BY name"
# select_numplan_sql = "SELECT * FROM NumPlan"
# select_devicenumplanmap_sql = "SELECT * FROM DeviceNumPlanMap"
#
# rows = parse_rows(axl_sql(select_devicenumplanmap_sql))
# for r in rows[:1]:
#     print(r)
# print(f"...rows returned: {len(rows)}")


