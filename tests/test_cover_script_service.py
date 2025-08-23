# tests/test_cover_script_service.py
import pytest
from app.features.cover_script.schemas import CoverScriptRequest
from app.features.cover_script.service import generate_cover_script

@pytest.mark.asyncio
async def test_generate_cover_script():
    req = CoverScriptRequest(
        title="Farting Through Dubai",
        synopsis="Roey navigates a plumbing disaster using his fart powers.",
        name="Roey Levartovsky",
        gender="male",
        page_count=6,
        theme="Pixar 3D animated cartoon style",
        user_answers_list={"What is Roey's job?":"plumber"}
    )
    res = await generate_cover_script(req)
    assert res.title
    assert res.tagline
    assert res.cover_art_description
    assert res.story_summary
