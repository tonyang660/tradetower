import requests


def get_json(url: str, params: dict | None = None, timeout: int = 15):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        payload = r.json()
        return payload, r.status_code, None
    except Exception as e:
        return None, None, str(e)


def post_json(url: str, payload: dict, timeout: int = 15):
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        data = r.json()
        return data, r.status_code, None
    except Exception as e:
        return None, None, str(e)

def get_json_proxy(url: str, params: dict | None = None, timeout: int = 20):
    payload, status_code, error = get_json(url, params=params, timeout=timeout)

    if error:
        return {"ok": False, "error": error}, 500

    if status_code != 200:
        return {"ok": False, "error": payload}, status_code or 500

    return payload, 200