import json, os, shlex, threading, time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from client import SCCPClient
from state import PhoneState
from config import config_path_from_here, load_config, save_config, is_config_complete
import logging
from utils.topology import cdp_sniffer, lldp_sniffer, start_topology_timer, poll_meraki_lsp, find_interface_for_target_ip


CmdFunc = Callable[[Any, str, List[str], Callable[[str], None]], None]

WILDCARD = "%W"

@dataclass
class Node:
    name: str
    help: str = ""
    func: Optional[str] = None
    optional: bool = False
    subs: List["Node"] = None

    @staticmethod
    def from_dict(d: dict) -> "Node":
        subs = [Node.from_dict(x) for x in d.get("subcommands", [])]
        return Node(
            name=d.get("command", ""),
            help=d.get("help", ""),
            func=d.get("function"),
            optional=bool(d.get("optional", False)),
            subs=subs,
        )

def load_cli_spec(path: str) -> List[Node]:
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    return [Node.from_dict(x) for x in spec]

def _match_token(token: str, choices: List[Node]) -> Tuple[Optional[Node], str]:
    """Abbrev match; returns (node, error). Wildcards are handled by caller."""
    cands = [n for n in choices if n.name != WILDCARD and n.name.lower().startswith(token.lower())]
    if not cands:
        return None, f"% Invalid input '{token}'"
    if len(cands) > 1:
        names = ", ".join(n.name for n in cands[:5])
        return None, f"% Ambiguous input '{token}' (could be: {names}...)"
    return cands[0], ""

def _find_wildcard(choices: List[Node]) -> Optional[Node]:
    for n in choices:
        if n.name == WILDCARD:
            return n
    return None

def _walk_context(nodes: list, tokens: list[str]):
    """
    Descend the tree as far as possible with tokens that are *complete* words.
    Returns (status, matches, curr_nodes), where:
      - status: "ok" | "ambiguous" | "nomatch"
      - matches: list[Node] when ambiguous (choices for that token)
      - curr_nodes: the node list at the current depth
    """
    curr = nodes
    for t in tokens:
        # candidates matching this token at this level
        cands = [n for n in curr if n.name != WILDCARD and n.name.lower().startswith(t.lower())]
        wc = _find_wildcard(curr)
        if cands:
            if len(cands) == 1:
                curr = cands[0].subs or []
            else:
                return "ambiguous", cands, curr
        elif wc:
            # wildcard consumes this token; descend
            curr = wc.subs or []
        else:
            return "nomatch", [], curr
    return "ok", [], curr

def _print_nodes(log, nodes: list[Node]):
    for n in nodes:
        name = n.name if n.name != WILDCARD else "<word>"
        log(f"  {name:<16} {n.help}")

def _candidates_at_level(curr: list[Node], prefix: str | None):
    if prefix is None or prefix == "":
        return curr[:]  # all
    return [n for n in curr if n.name != WILDCARD and n.name.lower().startswith(prefix.lower())]

def _unique_leaf_via_optionals(nodes: List["Node"]) -> Optional["Node"]:
    """
    From this level, see whether there is exactly one leaf (func and no subs)
    reachable by descending through nodes that are all optional=True.
    If yes, return that leaf Node; else None (either 0 or ambiguous >1).
    """
    found: List["Node"] = []

    def dfs(ns: List["Node"]) -> None:
        for n in ns or []:
            if not getattr(n, "optional", False):
                continue
            # If this optional node is itself a leaf with a function, collect it.
            if n.func and not (n.subs or []):
                found.append(n)
                continue
            # Only continue through optional children: we cannot skip required ones.
            opt_children = [c for c in (n.subs or []) if getattr(c, "optional", False)]
            if opt_children:
                dfs(opt_children)

    dfs(nodes)
    return found[0] if len(found) == 1 else None

def resolve_command_with_tokens(root: List[Node], words: List[str]) -> Tuple[Optional[str], List[str], List[str], str]:
    """
    Walk the tree with abbreviation support.
    Returns (func_name, tokens, captures, err)
      - tokens   : normalized path (abbrev expanded), including wildcard literals
      - captures : only wildcard values gathered along the path (what exec_* argv usually needs)
    """
    tokens: List[str] = []
    captures: List[str] = []
    nodes = root
    i = 0
    last_err = ""

    while True:
        if i >= len(words):
            # # No more input words; accept only if exactly one leaf function at this level.
            # leafs = [n for n in nodes if n.func and not n.subs]
            # if len(leafs) == 1:
            #     # Do NOT append leaf name here (user didn't type it).
            #     return leafs[0].func, tokens, captures, ""
            # return None, tokens, captures, last_err or "% Incomplete command"
            # First, accept if exactly one leaf func is available at this level.
            leafs = [n for n in nodes if n.func and not (n.subs or [])]
            if len(leafs) == 1:
                return leafs[0].func, tokens, captures, ""

            # Otherwise, try to complete using only optional nodes downstream.
            opt_leaf = _unique_leaf_via_optionals(nodes)
            if opt_leaf is not None:
                return opt_leaf.func, tokens, captures, ""

            return None, tokens, captures, last_err or "% Incomplete command"

        tok = words[i]

        # Try explicit/abbrev match first
        node, err = _match_token(tok, nodes)  # expected to return (node|None, err_msg)
        if node:
            # Special-case exit if you want
            if node.name.lower() == "exit":
                tokens.append(node.name)  # optional; harmless either way
                return "exec_exit", tokens, captures, ""

            tokens.append(node.name)  # record the normalized / full name

            if node.func and not node.subs:
                return node.func, tokens, captures, ""

            nodes = node.subs or []
            i += 1
            continue

        # Try wildcard branch for this level
        wc = _find_wildcard(nodes)
        if wc:
            tokens.append(tok)      # include the literal in normalized path
            captures.append(tok)    # and also capture it for handler argv
            nodes = wc.subs or []
            i += 1

            if wc.func and not wc.subs:
                return wc.func, tokens, captures, ""
            continue

        # No match
        last_err = err or "% Invalid input"
        return None, tokens, captures, last_err


def resolve_command(root: List[Node], words: List[str]) -> Tuple[Optional[str], List[str], str]:
    """
    Backward-compatible wrapper that returns (func_name, argv=captures_only, err),
    preserving the original expectation that argv contains ONLY wildcard values.
    """
    func, tokens, captures, err = resolve_command_with_tokens(root, words)
    return func, captures, err

# def resolve_command(root: List[Node], words: List[str]) -> Tuple[Optional[str], List[str], str]:
#     """
#     Walk the tree with abbreviation support. Returns (func_name, argv, err).
#     argv is the list of wildcard values gathered along the path.
#     """
#     argv: List[str] = []
#     nodes = root
#     i = 0
#     while True:
#         if i >= len(words):
#             # No more input words; accept only if we’re at a leaf with a function
#             funcs = [n for n in nodes if n.func]  # e.g., sole 'exit'
#             if len(funcs) == 1 and not funcs[0].subs:
#                 return funcs[0].func, argv, ""
#             return None, argv, "% Incomplete command"
#         tok = words[i]
#
#         # Try explicit match first
#         node, err = _match_token(tok, nodes)
#         if node:
#             if node.name.lower() == "exit":
#                 return "exec_exit", argv, ""
#             if node.func and not node.subs:
#                 # leaf with function; done
#                 return node.func, argv, ""
#             # descend and continue
#             nodes = node.subs or []
#             i += 1
#             continue
#
#         # Try wildcard branch for this level
#         wc = _find_wildcard(nodes)
#         if wc:
#             argv.append(tok)
#             nodes = wc.subs or []
#             i += 1
#             # If wildcard node itself has a function and no further subs, we can stop now
#             if wc.func and not wc.subs:
#                 return wc.func, argv, ""
#             continue
#
#         return None, argv, err or "% Invalid input"

class CLI:
    def __init__(self, client, spec: List[Node], funcs: Dict[str, CmdFunc], log):
        self.client = client
        self.spec = spec
        self.funcs = funcs
        self.log = log

    def exec_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if "?" in line:
            self.exec_help_query(line)
            return
        if line in ("help",):
            self.show_help(self.spec, "")
            return

        try:
            words = shlex.split(line)
        except ValueError as e:
            self.log(f"% Parse error: {e}")
            return

        # fname, argv, err = resolve_command(self.spec, words)
        fname, argv, caps, err = resolve_command_with_tokens(self.spec, words)

        if not fname:
            self.log(err)
            return
        fn = self.funcs.get(fname)
        if not fn:
            self.log(f"% Command not implemented: {fname}")
            return
        try:
            fn(self.client, line, argv, self.log)
        except Exception as e:
            self.log(f"% Error: {e}")

    def show_help(self, nodes: List[Node], prefix: str):
        for n in nodes:
            name = n.name if n.name != WILDCARD else "<word>"
            self.log(f"{prefix}{name:<16} {n.help}")
            if n.subs:
                pass  # context help on '?' at deeper levels could walk here

    def exec_help_query(self, line: str):
        """
        Cisco-like inline '?' help.
        - 'sh?'  -> list commands at root that match 'sh'
        - 'sh ?' -> after resolving 'sh', list its subcommands
        """
        s = line.rstrip()
        if not s:
            _print_nodes(self.log, self.spec)
            return

        # Case A: trailing space before ?  e.g. "show ?"
        if s.endswith("?") and len(s) >= 2 and s[-2].isspace():
            base = s[:-1].rstrip()
            words = shlex.split(base)
            status, matches, curr = _walk_context(self.spec, words)
            if status == "nomatch":
                self.log("% Invalid input")
                return
            if status == "ambiguous":
                _print_nodes(self.log, matches)
                return
            # ok: list all subcommands at this level (incl. wildcard placeholder)
            _print_nodes(self.log, curr)
            return

        # Case B: '?' appended to a token  e.g. "sh?" or "show ip?"
        # Remove ONE trailing '?', then split; the last token is the partial
        if s.endswith("?"):
            base = s[:-1]
        else:
            # '?' somewhere in the middle (rare); take text up to first '?'
            base = s.split("?", 1)[0]
        words = shlex.split(base)
        if not words:
            _print_nodes(self.log, self.spec)
            return

        partial = words[-1]
        parents = words[:-1]
        status, matches, curr = _walk_context(self.spec, parents)
        if status == "nomatch":
            self.log("% Invalid input")
            return
        if status == "ambiguous":
            _print_nodes(self.log, matches)
            return

        cands = _candidates_at_level(curr, partial)
        if cands:
            _print_nodes(self.log, cands)
            return
        # If nothing matches literal names but a wildcard exists, show it
        wc = _find_wildcard(curr)
        if wc:
            _print_nodes(self.log, [wc])
        else:
            self.log("% No matches")

    def candidates_for(self, tokens: list[str]) -> list[str]:
        """
        Return valid next-token candidates given the current tokens where
        the last token is considered partial. This mirrors your help logic.
        """
        # Reuse your existing helpers if available:
        #   status, matches, curr_nodes = _walk_context(self.spec, full_tokens)
        #   _candidates_at_level(curr_nodes, partial)
        # The following is a safe wrapper around those privates:

        partial = tokens[-1] if tokens else ""
        full_tokens = tokens[:-1] if tokens else []

        status, matches, curr = _walk_context(self.spec, full_tokens)
        if status == "nomatch":
            return []

        # If the last complete token was ambiguous, treat all matches as the level.
        if status == "ambiguous":
            level = matches
        else:
            level = curr

        # Names that start with the current partial
        return [n.name for n in level if n.name and n.name.startswith(partial)]


class CLIPhone:
    """
    Holds config + (optional) live client/state.
    Exposes connect()/disconnect(); unknown attrs delegate to client when connected.
    """
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("cli")
        self.config_path = config_path_from_here()
        self.config = load_config(self.config_path) or {}
        # ensure keys exist
        for k in ("server","mac","model","auto_connect"):
            self.config.setdefault(k, "" if k!="auto_connect" else True)

        self.client = None
        self.state = None
        self.stop_event = threading.Event()
        self.enable_cdp = False
        self.enable_lldp = False
        self.enable_lsp = False

        if self.config["auto_connect"] is True:
            self.connect(PhoneState, SCCPClient, register_timeout=10)

    def __getattr__(self, name):
        # delegate to client if connected
        c = object.__getattribute__(self, "client")
        if c is None:
            raise AttributeError(f"Not connected; attribute '{name}' not available")
        return getattr(c, name)

    def connect(self, PhoneState, SCCPClient, register_timeout: float = 30.0) -> bool:
        if self.client is not None:
            self.logger.info("Already connected.")
            return True
        if not is_config_complete(self.config):
            self.logger.error("Configuration incomplete. Set 'server', 'mac', and 'model' first.")
            return False

        server = self.config["server"]
        mac    = self.config["mac"]
        model  = self.config["model"]

        # Build state/client on demand
        self.state = PhoneState(server=server, mac=mac, model=model)
        self.client = SCCPClient(state=self.state)

        iface, src_ip, mac = find_interface_for_target_ip(self.state.server)
        self.state.interface = iface
        self.state.interface_mac = mac
        self.check_enable_topology()

        self.client.start()
        self.logger.info(f"({self.client.state.device_name}) Waiting for phone to register...")
        ok = self.state.is_registered.wait(timeout=register_timeout)
        if not ok:
            self.logger.error(f"({self.client.state.device_name}) Phone failed to register in time.")
            # tear down partially started client
            try: self.client.stop()
            except Exception: pass
            self.client = None
            self.state  = None
            return False

        self.logger.info("Connected.")
        return True

    def disconnect(self):
        if self.client is None:
            self.logger.debug("Not connected.")
            return
        try:
            self.client.stop()
        finally:
            self.client = None
            self.state  = None

    def save(self):
        save_config(self.config_path, self.config)
        self.logger.info(f"Configuration saved to {self.config_path}")

    def load(self):
        cfg = load_config(self.config_path)
        if cfg is None:
            self.logger.error(f"No config at {self.config_path}")
            return
        self.config.update(cfg)
        self.logger.info(f"Configuration loaded from {self.config_path}")

    def log(self, msg):
        self.logger.message(msg)

    def is_elevated(self):
        if os.name == 'nt':  # Windows
            import ctypes
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False
        else:  # Unix/Linux/macOS
            return os.geteuid() == 0

    def check_enable_topology(self):
        enable_cdp  = self.config.get("enable_cdp", False)
        enable_lldp  = self.config.get("enable_lldp", False)
        enable_lsp = self.config.get("enable_lsp", False)

        if enable_cdp or enable_lldp or enable_lsp:
            if self.is_elevated():
                if enable_cdp:
                    # Create and start the CDP thread
                    cdp_thread = threading.Thread(target=cdp_sniffer, args=(self.client,), daemon=True)
                    cdp_thread.start()
                if enable_lldp:
                    # Create and start the LLDP thread
                    lldp_thread = threading.Thread(target=lldp_sniffer, args=(self.client,), daemon=True)
                    lldp_thread.start()

                if enable_cdp or enable_lldp:
                    start_topology_timer(self.client, interval=30)
            else:
                self.logger.error("[TOPOLOGY] Run with elevated privileges in order to get/send CDP/LLDP data.")

        if enable_lsp:
            # Start the background monitor
            ap_monitor_thread = threading.Thread(target=poll_meraki_lsp, args=(60, 3, self.client,), daemon=True)
            ap_monitor_thread.start()

