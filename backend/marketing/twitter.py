import httpx
from utils.logger import log
from config import X_CLIENT_ID, X_CLIENT_SECRET, X_ACCESS_TOKEN, X_REFRESH_TOKEN

_TOKEN_URL = "https://api.oauth2.twitter.com/oauth2/token"
_API_URL = "https://api.twitter.com/2"


class TwitterClient:
    def __init__(self):
        self._access_token = X_ACCESS_TOKEN
        self._refresh_token = X_REFRESH_TOKEN
        self._http = httpx.Client(timeout=30)

    def _refresh_access_token(self) -> bool:
        if not self._refresh_token or not X_CLIENT_ID:
            log("[X] Cannot refresh — missing refresh_token or client_id")
            return False
        try:
            r = self._http.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": X_CLIENT_ID,
                "client_secret": X_CLIENT_SECRET,
                "refresh_token": self._refresh_token,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code == 200:
                data = r.json()
                self._access_token = data.get("access_token", self._access_token)
                if data.get("refresh_token"):
                    self._refresh_token = data["refresh_token"]
                log(f"[X] Token refreshed successfully")
                return True
            log(f"[X] Token refresh failed: {r.status_code} {r.text[:200]}")
            return False
        except Exception as e:
            log(f"[X] Token refresh error: {e}")
            return False

    def post_tweet(self, text: str) -> tuple[bool, str]:
        if not self._access_token:
            log("[X] No access token, attempting refresh")
            if not self._refresh_access_token():
                return False, "No access token available"

        for attempt in range(2):
            try:
                r = self._http.post(f"{_API_URL}/tweets", json={"text": text},
                    headers={"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"})
                if r.status_code == 201:
                    tweet_id = r.json().get("data", {}).get("id", "")
                    log(f"[X] Tweet posted: {tweet_id}")
                    return True, ""
                if r.status_code == 401 and attempt == 0:
                    log("[X] Token expired, refreshing")
                    if self._refresh_access_token():
                        continue
                err = f"{r.status_code} {r.text[:300]}"
                log(f"[X] Tweet failed: {err}")
                return False, err
            except Exception as e:
                log(f"[X] Tweet error: {e}")
                return False, str(e)
        return False, "Max retries exceeded"
