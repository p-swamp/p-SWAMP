import json
import pickle


def encoder(msg):
    if isinstance(msg, dict):
        try:
            return json.dumps(msg).encode("utf8")
        except TypeError:
            pass
    return json.dumps({"__bytes__": pickle.dumps(msg).decode("latin")}).encode("utf8")


def decoder(msg):
    msg_decoded = json.loads(msg)
    if "__bytes__" in msg_decoded:
        return pickle.loads(msg_decoded["__bytes__"].encode("latin"))
    return msg_decoded
