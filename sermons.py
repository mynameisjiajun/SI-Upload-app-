import json
import os
import uuid
from datetime import datetime
from typing import Optional

SERMONS_FILE = os.path.join(os.path.dirname(__file__), "sermons.json")


class SermonManager:
    def __init__(self):
        self._sermons: list[dict] = []
        self._load()

    def _load(self):
        if os.path.exists(SERMONS_FILE):
            with open(SERMONS_FILE, "r") as f:
                self._sermons = json.load(f)
        else:
            self._sermons = []

    def _save(self):
        with open(SERMONS_FILE, "w") as f:
            json.dump(self._sermons, f, indent=2)

    def get_sermons(self) -> list[dict]:
        """Returns all sermons sorted by date (soonest first)."""
        return sorted(self._sermons, key=lambda s: s["date"])

    def get_sermon(self, sermon_id: str) -> Optional[dict]:
        for s in self._sermons:
            if s["id"] == sermon_id:
                return s
        return None

    def add_sermon(self, date_str: str, title: str) -> dict:
        sermon = {
            "id": uuid.uuid4().hex[:8],
            "date": date_str,
            "title": title,
        }
        self._sermons.append(sermon)
        self._save()
        return sermon

    def remove_sermon(self, sermon_id: str) -> bool:
        before = len(self._sermons)
        self._sermons = [s for s in self._sermons if s["id"] != sermon_id]
        if len(self._sermons) < before:
            self._save()
            return True
        return False
