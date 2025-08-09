# api.py
import os, uuid, json, shutil, tempfile
from typing import List
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from main import generate_pages, make_pdf

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/generate")
async def generate_comic(
    background_tasks: BackgroundTasks,
    comic_title: str = Form(...),
    style: str = Form(...),
    character: str = Form(...),
    pages: str = Form(...),                 # JSON array of {id,title,panels:[]}
    image: UploadFile = File(None),         # optional image file
    return_pdf: bool = Form(False),
):
    workdir = tempfile.mkdtemp(prefix="job_")
    # auto-clean temp directory after response is sent
    background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)

    ref_path = None
    if image:
        if image.content_type not in {"image/png", "image/jpeg"}:
            raise HTTPException(400, "image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "ref.png")
        with open(ref_path, "wb") as f:
            f.write(await image.read())

    try:
        page_list = json.loads(pages)
        assert isinstance(page_list, list)
    except Exception:
        raise HTTPException(422, "pages must be a JSON array of page objects")

    prepared_prompts = []
    for page in page_list:
        pid = page["id"]; ptitle = page["title"]; panels = page["panels"]
        if not (isinstance(panels, list) and len(panels) == 4):
            raise HTTPException(422, "each page must have exactly 4 panels")

        character_block = character
        if ref_path:
            character_block = f"""{character}
REFERENCE: Match main character’s face to the uploaded image at {ref_path}"""

        numbered = [f"{i+1}) {txt}" for i, txt in enumerate(panels)]
        prompt = (
            f"{comic_title} — Page {pid}: {ptitle}\n"
            f"STYLE: {style}\n"
            f"CHARACTER: {character_block}\n"
            "4 panels:\n" + "\n".join(numbered)
        )
        prepared_prompts.append(prompt)

    files = generate_pages(
    prepared_prompts,
    max_workers=4,
    output_prefix=os.path.join(workdir, "page")  # <-- use output_prefix
    )
    if not files:
        raise HTTPException(500, "no pages were generated")

    if return_pdf:
        pdf_name = os.path.join(workdir, f"comic_{uuid.uuid4().hex}.pdf")
        make_pdf(files, pdf_name=pdf_name)
        return FileResponse(pdf_name, media_type="application/pdf", filename="comic.pdf")

    zip_base = os.path.join(workdir, "pages")
    shutil.make_archive(zip_base, "zip", workdir)
    return FileResponse(f"{zip_base}.zip", media_type="application/zip", filename="comic_pages.zip")
