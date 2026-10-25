"""Request and response schemas exposed by the API."""

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    inn: str = Field(pattern=r"^\d{10}(\d{2})?$")
    password: str = Field(min_length=1, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)


class DatasetSwitchRequest(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=500)


class AuthResponse(BaseModel):
    token: str
    role: Literal["admin", "company"]
    company_id: str | None
    display_name: str
    inn: str | None = None


class EventCreate(BaseModel):
    date: Date
    amount: float = Field(gt=0)
    direction: Literal["поступление", "списание"]
    category: str = Field(min_length=1, max_length=100)
    event_type: str = Field(default="пользовательское событие", max_length=100)
    description: str = Field(default="", max_length=1000)
    source: str = Field(default="ручной ввод", max_length=150)
    status: Literal["Ожидается", "Подтверждено", "Исполнено", "Отменено"] = "Ожидается"


class EventPatch(BaseModel):
    date: Date | None = None
    amount: float | None = Field(default=None, gt=0)
    direction: Literal["поступление", "списание"] | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    event_type: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    source: str | None = Field(default=None, max_length=150)
    status: Literal["Ожидается", "Подтверждено", "Исполнено", "Отменено"] | None = None


class CategoryPatch(BaseModel):
    category: str = Field(min_length=1, max_length=100)


class RecurringPatch(BaseModel):
    confirmed: bool


class EventOut(BaseModel):
    id: int
    company_id: str
    date: Date
    amount: float
    direction: Literal["поступление", "списание"]
    category: str
    event_type: str
    description: str
    source: str
    status: str


class DataHealth(BaseModel):
    status: str
    data_available: bool
    companies: int
    operations: int
    data_directory: str
    message: str
