from typing import Dict, List, Optional, Tuple
import re
from .data_models import DN, Ephone, EphoneButton, VoiceTranslationRule, VoiceTranslationRuleEntry, VoiceTranslationProfile, TelephonyService, DialPeer, TranslationProfileRef, Snapshot, ConfigSection


# ========= Parsing =========
DN_RE = re.compile(r'^\s*ephone-dn\s+(\d+)\s*$', re.IGNORECASE)
DN_NUMBER_RE = re.compile(r'^\s*number\s+(\S+)\s*$', re.IGNORECASE)
DN_MWI_RE = re.compile(r'^\s*mwi\s+(on|off)\s*$', re.IGNORECASE)
DN_LABEL_RE = re.compile(r'^\s*label\s+(?:"([^"]+)"|(.+))\s*$', re.IGNORECASE)
DN_NAME_RE  = re.compile(r'^\s*name\s+(?:"([^"]+)"|(.+))\s*$', re.IGNORECASE)

EPHONE_RE = re.compile(r'^\s*ephone\s+(\d+)\s*$', re.IGNORECASE)
EPHONE_MAC_RE = re.compile(r'^\s*mac-address\s+([0-9a-fA-F\.:-]+)\s*$', re.IGNORECASE)
EPHONE_TYPE_RE = re.compile(r'^\s*type\s+(\S+)\s*$', re.IGNORECASE)
EPHONE_SEC_RE = re.compile(r'^\s*device-security-mode\s+(\S+)\s*$', re.IGNORECASE)
EPHONE_BUTTON_RE = re.compile(r'^\s*button\s+(\d+)\s*:\s*(\d+)\s*$', re.IGNORECASE)
EPHONE_DESCRIPTION_RE = re.compile(r'^\s*description\s+(?:"([^"]+)"|(.+))\s*$', re.IGNORECASE)

# -------- telephony-service --------
TS_HEADER_RE = re.compile(r'^\s*telephony-service\s*$', re.IGNORECASE)
TS_MAX_EPHONES_RE = re.compile(r'^\s*max-ephones\s+(\d+)\s*$', re.IGNORECASE)
TS_MAX_DN_RE = re.compile(r'^\s*max-dn\s+(\d+)\s*$', re.IGNORECASE)
TS_IP_SRC_RE = re.compile(r'^\s*ip\s+source-address\s+(\S+)\s+port\s+(\d+)\s*$', re.IGNORECASE)
TS_DIALPLAN_RE = re.compile(r'^\s*dialplan-pattern\s+(.+)$', re.IGNORECASE)
TS_VOICEMAIL_RE = re.compile(r'^\s*voicemail\s+(.+)$', re.IGNORECASE)
TS_MAX_CONF_RE = re.compile(r'^\s*max-conferences\s+(\d+)\s+gain\s+(-?\d+)\s*$', re.IGNORECASE)
TS_TRANSFER_SYS_RE = re.compile(r'^\s*transfer-system\s+(\S+)\s*$', re.IGNORECASE)
TS_CNF_STAMP_RE = re.compile(r'^\s*create\s+cnf-files\s+version-stamp\s+(.+)$', re.IGNORECASE)

# -------- dial-peer --------
DP_HEADER_RE = re.compile(r'^\s*dial-peer\s+voice\s+(\d+)\s+(voip|pots)\s*$', re.IGNORECASE)
DP_DESC_RE = re.compile(r'^\s*description\s+(?:"([^"]+)"|(.+))\s*$', re.IGNORECASE)
DP_XLATE_IN_RE  = re.compile(r'^\s*translation-profile\s+incoming\s+(\S+)\s*$', re.IGNORECASE)
DP_XLATE_OUT_RE = re.compile(r'^\s*translation-profile\s+outgoing\s+(\S+)\s*$', re.IGNORECASE)
DP_DEST_RE = re.compile(r'^\s*destination-pattern\s+(\S+)\s*$', re.IGNORECASE)
DP_INCALL_RE = re.compile(r'^\s*incoming\s+called-number\s+(\S+)\s*$', re.IGNORECASE)
DP_SESS_PROTO_RE = re.compile(r'^\s*session\s+protocol\s+(\S+)\s*$', re.IGNORECASE)
DP_SESS_TARGET_RE = re.compile(r'^\s*session\s+target\s+(\S+)\s*$', re.IGNORECASE)
DP_DTMF_RE = re.compile(r'^\s*dtmf-relay\s+(\S+)\s*$', re.IGNORECASE)
DP_CODEC_RE = re.compile(r'^\s*codec\s+(\S+)\s*$', re.IGNORECASE)
DP_NO_VAD_RE = re.compile(r'^\s*no\s+vad\s*$', re.IGNORECASE)
DP_PORT_RE = re.compile(r'^\s*port\s+(\S+)\s*$', re.IGNORECASE)
DP_FWD_DIG_RE = re.compile(r'^\s*forward-digits\s+(\d+)\s*$', re.IGNORECASE)
DP_DID_RE = re.compile(r'^\s*direct-inward-dial\s*$', re.IGNORECASE)

# -------- voice translation-rule / profile --------
VTR_HEADER_RE = re.compile(r'^\s*voice\s+translation-rule\s+(\d+)\s*$', re.IGNORECASE)
# rule <seq> /.../ /.../   (handle escaped \/ inside)
VTR_RULE_RE = re.compile(
    r'^\s*rule\s+(\d+)\s+/((?:\\.|[^/])*)/\s+/((?:\\.|[^/])*)/\s*$',
    re.IGNORECASE
)

VTP_HEADER_RE = re.compile(r'^\s*voice\s+translation-profile\s+(\S+)\s*$', re.IGNORECASE)
# VTP_TRANSLATE_RE = re.compile(
#     r'^\s*translate\s+(called|calling|redirected|redirected-called)\s+(\d+)\s*$',
#     re.IGNORECASE
# )
VTP_TRANSLATE_RE = re.compile(
    r'^\s*translate\s+('
    r'called|calling|'
    r'redirect(?:ed)?(?:-called)?'
    r')\s+(\d+)\s*$',
    re.IGNORECASE
)

# These may appear in this section due to `| sec translation` matching lines elsewhere
TP_REF_RE = re.compile(r'^\s*translation-profile\s+(incoming|outgoing)\s+(\S+)\s*$', re.IGNORECASE)


def _cap2(m):
    """Return the first non-None capture group from a regex match (quoted or unquoted)."""
    if not m:
        return None
    g1, g2 = (m.group(1), m.group(2))
    return (g1 if g1 is not None else g2).strip()


def snip_translation_region(full_text: str) -> str:
    """
    Given output of 'show run | beg voice translation', return only the
    translation-rule/profile region. Keep both indented and left-justified
    subcommands like 'translate ...' or 'rule ...'. Stop at the first new
    top-level header that is not a translation header.
    """
    lines = full_text.splitlines()
    out = []
    started = False

    def is_top_header(s: str) -> bool:
        s = s.rstrip()
        if not s or s.strip() == "!":
            return False
        return not s.startswith(" ")  # left-justified

    def is_translation_header(s: str) -> bool:
        s = s.strip().lower()
        return s.startswith("voice translation-rule") or s.startswith("voice translation-profile")

    def is_translation_subcmd(s: str) -> bool:
        s = s.lstrip().lower()
        # Keep common subcommands even if not indented
        return s.startswith("translate ") or s.startswith("rule ")

    for raw in lines:
        line = raw.rstrip("\r")

        if not started:
            if is_translation_header(line):
                started = True
                out.append(line)
            continue

        # Once started, keep:
        if line.strip() == "" or line.strip() == "!":
            out.append(line)
            continue

        # New translation block header
        if is_translation_header(line):
            out.append(line)
            continue

        # Subcommands (indented OR left-justified)
        if line.startswith(" ") or is_translation_subcmd(line):
            out.append(line)
            continue

        # If we hit a new top-level non-translation header, stop.
        if is_top_header(line) and not is_translation_header(line):
            break

        # Fallback: keep anything else (rare)
        out.append(line)

    return "\n".join(out).strip()


def parse_cme_sections(text: str) -> Tuple[List[DN], List[Ephone]]:
    """
    Parse 'show run | sec ephone' output into DN and Ephone lists,
    capturing each block's raw configuration.
    """
    lines = [l.rstrip() for l in text.splitlines()]

    dns: Dict[int, DN] = {}
    ephones: Dict[int, Ephone] = {}

    current_dn_id = None
    current_ephone_id = None
    current_block_lines: List[str] = []  # accumulates raw lines for the active block

    def _flush_block():
        nonlocal current_dn_id, current_ephone_id, current_block_lines
        if current_dn_id is not None and current_dn_id in dns:
            # attach raw block
            # include a trailing "!" if IOS printed it in the section (often | sec removes it)
            dns[current_dn_id].raw_config = "\n".join(current_block_lines).strip() or None
        if current_ephone_id is not None and current_ephone_id in ephones:
            ephones[current_ephone_id].raw_config = "\n".join(current_block_lines).strip() or None
        current_block_lines = []

    for line in lines:
        if not line.strip():
            # allow blank lines inside blocks; keep them in raw
            if current_dn_id is not None or current_ephone_id is not None:
                current_block_lines.append(line)
            continue

        # New DN header?
        m = DN_RE.match(line)
        if m:
            # finishing previous block if any
            _flush_block()
            current_dn_id = int(m.group(1))
            current_ephone_id = None
            dns[current_dn_id] = DN(id=current_dn_id, number="", mwi=None, raw_config=None, label=None, name=None)
            current_block_lines = [line]  # start raw with header
            continue

        # New ephone header?
        m = EPHONE_RE.match(line)
        if m:
            _flush_block()
            current_ephone_id = int(m.group(1))
            current_dn_id = None
            ephones[current_ephone_id] = Ephone(
                id=current_ephone_id, mac=None, type=None, description=None, security_mode=None, buttons=[], raw_config=None
            )
            current_block_lines = [line]
            continue

        # Inside a DN block
        if current_dn_id is not None:
            current_block_lines.append(line)
            if (n := DN_NUMBER_RE.match(line)):
                dns[current_dn_id].number = n.group(1)
            elif (mwi := DN_MWI_RE.match(line)):
                dns[current_dn_id].mwi = mwi.group(1).lower()
            elif (label := DN_LABEL_RE.match(line)):
                dns[current_dn_id].label = _cap2(label)
            elif (name := DN_NAME_RE.match(line)):
                dns[current_dn_id].name = _cap2(name)
            continue

        # Inside an ephone block
        if current_ephone_id is not None:
            current_block_lines.append(line)
            if (mm := EPHONE_MAC_RE.match(line)):
                ephones[current_ephone_id].mac = mm.group(1).lower()
            elif (tt := EPHONE_TYPE_RE.match(line)):
                ephones[current_ephone_id].type = tt.group(1)
            elif (ss := EPHONE_SEC_RE.match(line)):
                ephones[current_ephone_id].security_mode = ss.group(1)
            elif (bb := EPHONE_BUTTON_RE.match(line)):
                line_idx = int(bb.group(1))
                dn_id = int(bb.group(2))
                ephones[current_ephone_id].buttons.append(EphoneButton(line=line_idx, dn_id=dn_id))
            elif (description := EPHONE_DESCRIPTION_RE.match(line)):
                ephones[current_ephone_id].description = _cap2(description)
            continue

        # Lines outside known blocks are ignored

    # Flush the last open block at EOF
    _flush_block()

    # Normalize to lists sorted by id
    return (
        [dns[k] for k in sorted(dns.keys())],
        [ephones[k] for k in sorted(ephones.keys())],
    )


def parse_telephony_service(text: str) -> Optional[TelephonyService]:
    """
    Parse 'show run | sec telephony-service' (typically one block).
    Returns a TelephonyService or None if not found.
    """
    if not text.strip():
        return None

    lines = [l.rstrip() for l in text.splitlines()]
    ts = None
    block_lines: List[str] = []
    in_block = False

    for line in lines:
        if not in_block:
            if TS_HEADER_RE.match(line):
                in_block = True
                ts = TelephonyService(
                    raw_config=None,
                    dialplan_patterns=[]
                )
                block_lines = [line]
            continue

        # inside the block
        if in_block:
            # Usually | sec gives only the section, but we’ll just keep consuming all lines we got
            block_lines.append(line)

            if (m := TS_MAX_EPHONES_RE.match(line)):
                ts.max_ephones = int(m.group(1))
            elif (m := TS_MAX_DN_RE.match(line)):
                ts.max_dn = int(m.group(1))
            elif (m := TS_IP_SRC_RE.match(line)):
                ts.ip_source_address = m.group(1)
                ts.ip_source_port = int(m.group(2))
            elif (m := TS_DIALPLAN_RE.match(line)):
                ts.dialplan_patterns.append(m.group(1).strip())
            elif (m := TS_VOICEMAIL_RE.match(line)):
                ts.voicemail = m.group(1).strip()
            elif (m := TS_MAX_CONF_RE.match(line)):
                ts.max_conferences = int(m.group(1))
                ts.conference_gain = int(m.group(2))
            elif (m := TS_TRANSFER_SYS_RE.match(line)):
                ts.transfer_system = m.group(1).strip()
            elif (m := TS_CNF_STAMP_RE.match(line)):
                ts.cnf_version_stamp = m.group(1).strip()

    if ts:
        ts.raw_config = "\n".join(block_lines).strip()
    return ts


def parse_dial_peers(text: str) -> List[DialPeer]:
    """
    Parse 'show run | sec dial-peer' into a list of DialPeer objects with raw_config per peer.
    """
    peers: Dict[int, DialPeer] = {}
    lines = [l.rstrip() for l in text.splitlines()]
    current_id = None
    current_block: List[str] = []

    def flush():
        nonlocal current_id, current_block
        if current_id is not None and current_id in peers:
            peers[current_id].raw_config = "\n".join(current_block).strip()
        current_id = None
        current_block = []

    for line in lines:
        if not line.strip():
            if current_id is not None:
                current_block.append(line)
            continue

        # New peer header?
        m = DP_HEADER_RE.match(line)
        if m:
            flush()
            pid = int(m.group(1))
            kind = m.group(2).lower()
            peers[pid] = DialPeer(id=pid, kind=kind)
            current_id = pid
            current_block = [line]
            continue

        # Inside a peer
        if current_id is not None:
            current_block.append(line)
            dp = peers[current_id]

            if (mm := DP_DESC_RE.match(line)):
                dp.description = _cap2(mm)
            elif (mm := DP_XLATE_IN_RE.match(line)):
                dp.translation_profile_in = mm.group(1)
            elif (mm := DP_XLATE_OUT_RE.match(line)):
                dp.translation_profile_out = mm.group(1)
            elif (mm := DP_DEST_RE.match(line)):
                dp.destination_pattern = mm.group(1)
            elif (mm := DP_INCALL_RE.match(line)):
                dp.incoming_called_number = mm.group(1)
            elif (mm := DP_SESS_PROTO_RE.match(line)):
                dp.session_protocol = mm.group(1)
            elif (mm := DP_SESS_TARGET_RE.match(line)):
                dp.session_target = mm.group(1)
            elif (mm := DP_DTMF_RE.match(line)):
                dp.dtmf_relay = mm.group(1)
            elif (mm := DP_CODEC_RE.match(line)):
                dp.codec = mm.group(1)
            elif DP_NO_VAD_RE.match(line):
                dp.no_vad = True
            elif (mm := DP_PORT_RE.match(line)):
                dp.port = mm.group(1)
            elif (mm := DP_FWD_DIG_RE.match(line)):
                dp.forward_digits = int(mm.group(1))
            elif DP_DID_RE.match(line):
                dp.direct_inward_dial = True
            continue

        # Lines outside a peer block are ignored

    flush()
    return [peers[k] for k in sorted(peers.keys())]


def parse_translation_sections(text: str) -> Tuple[List[VoiceTranslationRule], List[VoiceTranslationProfile], List[TranslationProfileRef]]:
    """
    Parse 'show run | sec translation' into:
      - translation_rules (voice translation-rule <n> ... )
      - translation_profiles (voice translation-profile <name> ... )
      - translation_refs: loose 'translation-profile incoming/outgoing <NAME>' lines
    """
    rules: Dict[int, VoiceTranslationRule] = {}
    profiles: Dict[str, VoiceTranslationProfile] = {}
    refs: List[TranslationProfileRef] = []

    lines = [l.rstrip() for l in text.splitlines()]

    # Track an active block (either a rule id or a profile name)
    current_rule_id: Optional[int] = None
    current_profile_name: Optional[str] = None
    current_block: List[str] = []

    def flush():
        nonlocal current_rule_id, current_profile_name, current_block
        if current_rule_id is not None and current_rule_id in rules:
            rules[current_rule_id].raw_config = "\n".join(current_block).strip() or None
        if current_profile_name is not None and current_profile_name in profiles:
            profiles[current_profile_name].raw_config = "\n".join(current_block).strip() or None
        current_rule_id = None
        current_profile_name = None
        current_block = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # keep blank lines inside blocks as part of raw
            if current_rule_id is not None or current_profile_name is not None:
                current_block.append(line)
            continue

        # drop separator lines entirely
        if stripped == "!":
            # treat as block separator; do not record in raw_config or other_lines
            # (also helps collapse multiple '!' between blocks)
            continue

        # New 'voice translation-rule N' header?
        m = VTR_HEADER_RE.match(line)
        if m:
            flush()
            rid = int(m.group(1))
            rules[rid] = VoiceTranslationRule(id=rid, raw_config=None, rules=[])
            current_rule_id = rid
            current_block = [line]
            continue

        # New 'voice translation-profile NAME' header?
        m = VTP_HEADER_RE.match(line)
        if m:
            flush()
            name = m.group(1)
            profiles[name] = VoiceTranslationProfile(name=name, raw_config=None, other_lines=[])
            current_profile_name = name
            current_block = [line]
            continue

        # Loose translation-profile ref lines (incoming/outgoing) — keep them for cross-refs
        m = TP_REF_RE.match(line)
        if m and current_rule_id is None and current_profile_name is None:
            refs.append(TranslationProfileRef(direction=m.group(1).lower(), name=m.group(2), raw_line=line))
            continue

        # Inside a translation-rule block
        if current_rule_id is not None:
            current_block.append(line)
            if (rm := VTR_RULE_RE.match(line)):
                seq = int(rm.group(1))
                match = rm.group(2).replace(r"\/", "/")
                replace = rm.group(3).replace(r"\/", "/")
                rules[current_rule_id].rules.append(VoiceTranslationRuleEntry(seq=seq, match=match, replace=replace))
            continue

        # Inside a translation-profile block
        if current_profile_name is not None:
            current_block.append(line)
            if (tm := VTP_TRANSLATE_RE.match(line)):
                kind = tm.group(1).lower()
                num = int(tm.group(2))
                prof = profiles[current_profile_name]

                if kind == "called":
                    prof.translate_called = num
                elif kind == "calling":
                    prof.translate_calling = num
                elif kind.startswith("redirect"):
                    # covers "redirected" and "redirect[ed]-called"
                    if "called" in kind:
                        prof.translate_redirected_called = num
                    else:
                        prof.translate_redirected = num
            else:
                profiles[current_profile_name].other_lines.append(line.strip())
            continue

        # Otherwise ignore

    flush()

    return (
        [rules[k] for k in sorted(rules.keys())],
        [profiles[k] for k in sorted(profiles.keys(), key=str.lower)],
        refs
    )

