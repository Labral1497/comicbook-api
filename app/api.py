# api.py
import os, uuid, json, shutil
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app import make_job_dir, generate_pages, make_pdf, logger, config, ComicRequest

log = logger.get_logger(__name__)
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
    payload: str = Form(...),            # JSON string for ComicRequest
    image: UploadFile = File(None),      # optional file upload
):
    workdir = make_job_dir()
    log.info(f"Working directory created: {workdir}")
    # auto-clean temp directory after response is sent
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, workdir, ignore_errors=True)

    # Parse & validate JSON
    try:
        req = ComicRequest(**json.loads(payload))
    except Exception as e:
        raise HTTPException(422, f"Invalid payload JSON: {e}")

    ref_path = None
    if image:
        if image.content_type not in {"image/png", "image/jpeg"}:
            log.error("Invalid image format")
            raise HTTPException(400, "image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "ref.png")
        with open(ref_path, "wb") as f:
            f.write(await image.read())
        log.info(f"Reference image saved at: {ref_path}")

    # log.info(f"Pages JSON received: {pages}")
    prepared_prompts = []
    for page in req.pages:
        character_block = req.character
        if ref_path:
            character_block = f"""{req.character}
REFERENCE: Match main character’s face to the uploaded image at {ref_path}"""
        elif req.image_ref:
            character_block = f"""{req.character}
REFERENCE: Match main character’s face to: {req.image_ref}"""

        numbered = [f"{i+1}) {txt}" for i, txt in enumerate(page.panels)]
        prompt = (
            f"{req.comic_title} — Page {page.id}: {page.title}\n"
            f"STYLE: {req.style}\n"
            f"CHARACTER: {character_block}\n"
            "4 panels:\n" + "\n".join(numbered)
        )
        prepared_prompts.append(prompt)

    # Generate images
    files = generate_pages(
        prepared_prompts,
        output_prefix=os.path.join(workdir, "page"),
        # model/size/max_workers default from config; override here if you want
    )
    if not files:
        raise HTTPException(500, "no pages were generated")

    # Return PDF or ZIP
    if req.return_pdf:
        pdf_name = os.path.join(workdir, f"comic_{uuid.uuid4().hex}.pdf")
        make_pdf(files, pdf_name=pdf_name)
        return FileResponse(pdf_name, media_type="application/pdf", filename="comic.pdf")

    zip_base = os.path.join(workdir, "pages")
    shutil.make_archive(zip_base, "zip", workdir)
    return FileResponse(f"{zip_base}.zip", media_type="application/zip", filename="comic_pages.zip")
