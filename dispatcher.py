message_handlers = {}


def register_handler(msg_id, name=None):
    def decorator(func):
        message_handlers[msg_id] = {
            "name": name or func.__name__,
            "handler": func,
        }
        return func
    return decorator


def dispatch_message(client, msg_id, payload):
    if not client.running or msg_id is None:
        return

    entry = message_handlers.get(msg_id)
    if entry:
        name = entry["name"]
        handler = entry["handler"]
        client.logger.debug(f"Dispatching {name} (msg_id=0x{msg_id:04X})")
        handler(client, payload)
    else:
        client.logger.warning(f"Unhandled message ID: 0x{msg_id:04X} / {msg_id}")


def get_message_name(msg_id):
    entry = message_handlers.get(msg_id)
    if entry:
        return entry["name"]
    return f"Unknown (0x{msg_id:04X})"
