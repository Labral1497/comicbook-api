# app/features/story_ideas/schemas.py
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class StoryIdeasRequest(BaseModel):
    name: str
    theme: str
    gender: Optional[str] = None
    purpose_of_gift: Optional[str] = None
    user_answers_list: Dict[str, str] = Field(default_factory=dict, description="Comedic Q&A pairs")

class StoryIdea(BaseModel):
    title: str
    synopsis: str

class StoryIdeasResponse(BaseModel):
    ideas: List[StoryIdea]
