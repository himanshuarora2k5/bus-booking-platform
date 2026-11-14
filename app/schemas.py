"""Input rules for the booking request. Bad input is rejected here with HTTP 422."""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PHONE_RE = re.compile(r"^[6-9][0-9]{9}$")  # Indian mobile number: 10 digits, starts with 6-9
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,59}$")


class Passenger(BaseModel):
    name: str
    age: int = Field(ge=1, le=120)
    gender: Literal["M", "F", "O"]
    seat_no: str = Field(pattern=r"^[0-9]{1,2}[A-Za-z]$")

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not NAME_RE.match(v):
            raise ValueError("name must be 2-60 letters (spaces, . ' - allowed)")
        return v

    @field_validator("seat_no")
    @classmethod
    def upper_seat(cls, v: str) -> str:
        return v.upper()


class BookingRequest(BaseModel):
    trip_id: int = Field(gt=0)
    travel_date: date
    boarding_stop: str = Field(min_length=1, max_length=60)
    drop_stop: str = Field(min_length=1, max_length=60)
    contact_phone: str
    passengers: list[Passenger] = Field(min_length=1, max_length=6)

    @field_validator("contact_phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        if not PHONE_RE.match(v):
            raise ValueError("contact_phone must be a 10-digit Indian mobile number")
        return v

    @model_validator(mode="after")
    def no_duplicate_seats(self) -> "BookingRequest":
        seats = [p.seat_no for p in self.passengers]
        if len(seats) != len(set(seats)):
            raise ValueError("the same seat appears twice in one booking")
        return self
