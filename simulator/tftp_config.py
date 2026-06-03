"""Generate minimal Cisco-style SCCP phone TFTP XML configs."""

from __future__ import annotations

import re
from xml.sax.saxutils import escape


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
