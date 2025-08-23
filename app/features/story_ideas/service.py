# app/features/story_ideas/service.py
import json
from app.lib.openai_client import client
from app.lib.json_tools import extract_json_block
from app.features.story_ideas.schemas import StoryIdeasRequest, StoryIdeasResponse, StoryIdea

SYSTEM = (
    "You are a witty, concise copywriter. "
    "Return STRICT JSON only — exactly a JSON array of three objects, each with 'title' and 'synopsis' (strings). "
    "No extra text, no comments, no markdown."
)

def _traits_from_answers(user_answers_list) -> str:
    return ", ".join(f"{q} - {a}" for q, a in user_answers_list.items()) if user_answers_list else ""

async def generate_story_ideas(req: StoryIdeasRequest) -> StoryIdeasResponse:
    gender  = req.gender or "unspecified"
    purpose = req.purpose_of_gift or "general gift"
    traits  = _traits_from_answers(req.user_answers_list)

    from .prompt import build_story_ideas_prompt
    prompt = build_story_ideas_prompt(name=req.name, gender=gender, theme=req.theme, purpose=purpose, traits=traits)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.9,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(extract_json_block(raw))
    ideas = [StoryIdea(title=i["title"], synopsis=i["synopsis"]) for i in data[:3]]
    return StoryIdeasResponse(ideas=ideas)
