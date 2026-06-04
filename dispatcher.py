from utils.skinny_messages import get_message_name, register_skinny_message_name

message_handlers = {}


def register_handler(msg_id, name=None):
    def decorator(func):
        resolved = name or func.__name__
        register_skinny_message_name(msg_id, resolved)
        message_handlers[msg_id] = {
            "name": resolved,
            "handler": func,
        }
        return func
    return decorator


def dispatch_message(client, msg_id, payload):
    if not client.running or msg_id is None:
        return

    from utils.logs import log_skinny_wire

    entry = message_handlers.get(msg_id)
    name = entry["name"] if entry else get_message_name(msg_id)
    log_skinny_wire(
        client.logger,
        client.state.device_name,
        "RECV",
        msg_id,
        name,
        len(payload),
    )
    if entry:
        client.logger.debug(f"Dispatching {name} (msg_id=0x{msg_id:04X})")

    if entry:
        handler = entry["handler"]
        handler(client, payload)
    else:
        client.logger.warning(f"Unhandled message ID: 0x{msg_id:04X} / {msg_id}")
