# tests/test_story_ideas_service.py
import pytest
from app.features.story_ideas.schemas import StoryIdeasRequest
from app.features.story_ideas.service import generate_story_ideas

@pytest.mark.asyncio
async def test_generate_story_ideas_basic():
    req = StoryIdeasRequest(
        name="Roey",
        theme="Pixar 3D animated cartoon style",
        gender="male",
        purpose_of_gift="birthday gag gift",
        user_answers_list={"What is Roey's job?":"plumber"}
    )
    res = await generate_story_ideas(req)
    assert len(res.ideas) == 3
    assert all(hasattr(i, "title") and hasattr(i, "synopsis") for i in res.ideas)
