import re
from datetime import datetime
from typing import Optional

from dateutil import parser
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class AuditMixin(BaseModel):
    updated_at: datetime = Field(default_factory=datetime.now)


class TransfermarktBaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    @field_validator(
        "date_of_birth",
        "joined_on",
        "contract",
        "founded_on",
        "members_date",
        "from_date",
        "until_date",
        "date",
        "contract_expires",
        "joined",
        "retired_since",
        mode="before",
        check_fields=False,
    )
    def parse_str_to_date(cls, v: str):
        if not v:
            return None
        try:
            # Deutsches Datumsformat "01.01.2025" → dayfirst=True
            return parser.parse(v, dayfirst=True).date()
        except (parser.ParserError, ValueError, OverflowError):
            return None

    @field_validator(
        "current_market_value",
        "current_transfer_record",
        "market_value",
        "mean_market_value",
        "members",
        "total_market_value",
        "age",
        "goals",
        "assists",
        "yellow_cards",
        "red_cards",
        "minutes_played",
        "fee",
        "appearances",
        "games_missed",
        mode="before",
        check_fields=False,
    )
    def parse_str_to_int(cls, v: str) -> Optional[int]:
        if not v or not any(char.isdigit() for char in v):
            return None

        # Deutsche Zusatztexte entfernen ("Letzte Änderung: ...", "last change: ...")
        v = re.split(r"(?:letzte|last)\s", v, flags=re.IGNORECASE)[0]

        # Clean up HTML tags if present
        if "<" in str(v):
            matches = re.findall(r"€([\d,.]+[kmb]?)", v.lower())
            if not matches:
                return None
            value_str = matches[0]
        else:
            value_str = v.lower().replace("€", "").replace("+", "").replace("'", "").strip()

        # Deutsche Formate: "Mio." → m, "Tsd." → k, "Mrd." → bn
        value_str = re.sub(r"mio\.?", "m", value_str)
        value_str = re.sub(r"tsd\.?", "k", value_str)
        value_str = re.sub(r"mrd\.?", "bn", value_str)

        # Deutsches Dezimalkomma: "15,00m" → "15.00m" (nur wenn Komma als Dezimal)
        value_str = re.sub(r"(\d),(\d{1,2})([mkb]|bn|$)", r"\1.\2\3", value_str)

        # Restnoise entfernen
        value_str = re.sub(r"[^\d.kmbn]", "", value_str)

        if not value_str or not any(c.isdigit() for c in value_str):
            return None

        # Deutscher Tausender-Separator: "2.970" → "2970", "1.234.567" → "1234567".
        # Nur wenn kein Suffix (k/m/bn) und Muster strikt Tausender-Gruppierung ist.
        # Ohne diesen Schritt macht int(float("2.970")) = 2 (Bug bei minutesPlayed/appearances).
        if not any(s in value_str for s in ("k", "m", "bn", "b")) and re.match(r"^\d{1,3}(?:\.\d{3})+$", value_str):
            value_str = value_str.replace(".", "")

        if "k" in value_str:
            return int(float(value_str.replace("k", "")) * 1_000)
        elif "m" in value_str:
            return int(float(value_str.replace("m", "")) * 1_000_000)
        elif "bn" in value_str:
            return int(float(value_str.replace("bn", "")) * 1_000_000_000)
        elif "b" in value_str:
            return int(float(value_str.replace("b", "")) * 1_000_000_000)
        else:
            return int(float(value_str))

    @field_validator("height", mode="before", check_fields=False)
    def parse_height(cls, v: str) -> Optional[int]:
        if not v or not any(char.isdigit() for char in v):
            return None
        return int(v.replace(",", "").replace("m", "").replace("،", ""))

    @field_validator("days", mode="before", check_fields=False)
    def parse_days(cls, v: str) -> Optional[int]:
        days = "".join(filter(str.isdigit, v))
        return int(days) if days else None
