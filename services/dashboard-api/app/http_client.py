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
