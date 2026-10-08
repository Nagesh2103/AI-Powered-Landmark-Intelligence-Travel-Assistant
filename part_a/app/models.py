from typing import Optional
from pydantic import BaseModel, Field


class Review(BaseModel):
    author: str
    rating: Optional[float] = None
    text: str


class PlaceDetails(BaseModel):
    name: str
    address: Optional[str] = None
    rating: Optional[float] = None
    total_reviews: int = 0
    reviews: list[Review] = Field(default_factory=list)
    source_query: str