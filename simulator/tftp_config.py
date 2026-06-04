"""Generate minimal Cisco-style SCCP phone TFTP XML configs."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

_CUCM_URL_PATHS = {
    "authenticationURL": "authenticate.asp",
    "directoryURL": "xmldirectory.asp",
    "informationURL": "GetTelecasterHelpText.asp",
    "servicesURL": "getservicesmenu.asp",
    "idleURL": "idle.asp",
    "messagesURL": "messages.asp",
    "proxyServerURL": "proxy.asp",
}


def is_cucm_sep_config(text: str) -> bool:
    """Heuristic: full CUCM export vs our minimal generator output."""
    return "<loadInformation>" in text and "<devicePool" in text


def patch_sep_config_for_sim(
    text: str,
    *,
    cm_host: str,
    directory_number: str,
    skinny_port: int = 2000,
    cip_port: int = 8088,
) -> str:
    """Point CM + CCMCIP URLs at the simulator; ensure a line block exists."""
    host = cm_host
    cip_base = f"http://{host}:{cip_port}/CCMCIP"

    text = re.sub(
        r"<processNodeName>[^<]*</processNodeName>",
        f"<processNodeName>{escape(host)}</processNodeName>",
        text,
        count=1,
    )
    text = re.sub(
        r"<ethernetPhonePort>\d+</ethernetPhonePort>",
        f"<ethernetPhonePort>{skinny_port}</ethernetPhonePort>",
        text,
        count=1,
    )
    for tag, path in _CUCM_URL_PATHS.items():
        text = re.sub(
            rf"<{tag}>[^<]*</{tag}>",
            f"<{tag}>{cip_base}/{path}</{tag}>",
            text,
            count=1,
        )

    # Do not rewrite webAccess: on CUCM, 0 often means enabled (7912 ignores this tag
    # for CGI anyway — see README / utils.phone_web_probe; gk* profile OpFlags bit 7).


    if "<lines>" not in text and "</device>" in text:
        dn = escape(directory_number)
        lines = f"""
  <lines>
    <line button="1">
      <featureID>9</featureID>
      <featureLabel>{dn}</featureLabel>
      <name>{dn}</name>
      <displayName>{dn}</displayName>
      <e164Mask>{dn}</e164Mask>
    </line>
  </lines>
"""
        text = text.replace("</device>", lines + "</device>", 1)

    return text


def _sep_name_from_filename(filename: str) -> str | None:
    base = filename.replace("\\", "/").split("/")[-1]
    m = re.match(r"^(SEP[0-9A-Fa-f]{12})\.cnf\.xml$", base)
    return m.group(1).upper() if m else None


def build_xml_default(cm_host: str, skinny_port: int = 2000) -> str:
    """Fallback config when a per-device SEP file is missing."""
    host = escape(cm_host)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<device>
  <deviceProtocol>SCCP</deviceProtocol>
  <fullConfig>true</fullConfig>
  <devicePool>
    <callManagerGroup>
      <members>
        <member priority="0">
          <callManager>
            <ports>
              <ethernetPhonePort>{skinny_port}</ethernetPhonePort>
            </ports>
            <processNodeName>{host}</processNodeName>
          </callManager>
        </member>
      </members>
    </callManagerGroup>
  </devicePool>
  <loadInformation></loadInformation>
  <versionStamp>{{Jan 01 2002 00:00:00}}</versionStamp>
  <userLocale>
    <name>English_United_States</name>
    <langCode>en</langCode>
  </userLocale>
  <networkLocale>United_States</networkLocale>
</device>
"""


def build_sep_config(
    device_name: str,
    directory_number: str,
    cm_host: str,
    *,
    skinny_port: int = 2000,
    load_information: str = "",
) -> str:
    """Per-phone config with one line button and auto-assigned DN."""
    host = escape(cm_host)
    dn = escape(directory_number)
    dev = escape(device_name)
    load = escape(load_information)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<device>
  <deviceProtocol>SCCP</deviceProtocol>
  <fullConfig>true</fullConfig>
  <devicePool>
    <callManagerGroup>
      <members>
        <member priority="0">
          <callManager>
            <ports>
              <ethernetPhonePort>{skinny_port}</ethernetPhonePort>
            </ports>
            <processNodeName>{host}</processNodeName>
          </callManager>
        </member>
      </members>
    </callManagerGroup>
  </devicePool>
  <lines>
    <line button="1">
      <featureID>9</featureID>
      <featureLabel>{dn}</featureLabel>
      <name>{dn}</name>
      <displayName>{dn}</displayName>
      <e164Mask>{dn}</e164Mask>
    </line>
  </lines>
  <loadInformation>{load}</loadInformation>
  <versionStamp>{{Jan 01 2002 00:00:00}}</versionStamp>
  <userLocale>
    <name>English_United_States</name>
    <langCode>en</langCode>
  </userLocale>
  <networkLocale>United_States</networkLocale>
  <!-- {dev} -->
</device>
"""
