from dataclasses import dataclass
from typing import List, Optional


# ========= Data models =========
@dataclass
class DN:
    id: int
    number: str
    mwi: Optional[str] = None
    name: Optional[str] = None
    label: Optional[str] = None
    raw_config: Optional[str] = None

@dataclass
class EphoneButton:
    line: int
    dn_id: int

@dataclass
class Ephone:
    id: int
    mac: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    security_mode: Optional[str] = None
    buttons: List[EphoneButton] = None
    raw_config: Optional[str] = None

@dataclass
class TelephonyService:
    raw_config: Optional[str] = None
    max_ephones: Optional[int] = None
    max_dn: Optional[int] = None
    ip_source_address: Optional[str] = None  # "172.16.0.1"
    ip_source_port: Optional[int] = None     # 2000
    dialplan_patterns: List[str] = None      # preserve full line after "dialplan-pattern"
    voicemail: Optional[str] = None          # "9000"
    max_conferences: Optional[int] = None
    conference_gain: Optional[int] = None    # -6
    transfer_system: Optional[str] = None    # "full-consult"
    cnf_version_stamp: Optional[str] = None  # full text after "create cnf-files version-stamp ..."

@dataclass
class DialPeer:
    id: int
    kind: str                         # "voip" or "pots"
    raw_config: Optional[str] = None
    description: Optional[str] = None
    translation_profile_in: Optional[str] = None
    translation_profile_out: Optional[str] = None
    destination_pattern: Optional[str] = None
    incoming_called_number: Optional[str] = None
    session_protocol: Optional[str] = None
    session_target: Optional[str] = None     # e.g. "ipv4:172.16.0.11" or a DNS/SIP uri
    dtmf_relay: Optional[str] = None         # e.g. "sip-notify"
    codec: Optional[str] = None              # e.g. "g711ulaw"
    no_vad: bool = False
    port: Optional[str] = None               # e.g. "0/1/0:23"
    forward_digits: Optional[int] = None
    direct_inward_dial: bool = False

@dataclass
class VoiceTranslationRuleEntry:
    seq: int
    match: str
    replace: str

@dataclass
class VoiceTranslationRule:
    id: int
    raw_config: Optional[str] = None
    rules: List[VoiceTranslationRuleEntry] = None  # list of entries (rule lines)

@dataclass
class VoiceTranslationProfile:
    name: str
    raw_config: Optional[str] = None
    # Common parsed knobs (optional—kept generic, extend as needed)
    translate_called: Optional[int] = None
    translate_calling: Optional[int] = None
    translate_redirected: Optional[int] = None
    translate_redirected_called: Optional[int] = None
    other_lines: List[str] = None  # keep anything we didn't model

@dataclass
class TranslationProfileRef:
    direction: str  # "incoming" or "outgoing"
    name: str       # profile name
    raw_line: str

@dataclass
class ConfigSection:
    dn_range_start: Optional[int] = None
    dn_range_end: Optional[int] = None
    next_dn_number: Optional[int] = None
    next_ephone_id: Optional[int] = None
    next_dn_id: Optional[int] = None

@dataclass
class Snapshot:
    device_host: str
    device_hostname: Optional[str]
    collected_at: float
    dns: List[DN]
    ephones: List[Ephone]
    config: ConfigSection
    telephony_service: Optional[TelephonyService] = None
    dial_peers: List[DialPeer] = None
    translation_rules: List[VoiceTranslationRule] = None
    translation_profiles: List[VoiceTranslationProfile] = None
    translation_refs: List[TranslationProfileRef] = None