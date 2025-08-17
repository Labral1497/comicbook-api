# api.py
import base64
import os, uuid, json, shutil
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app import (
    make_job_dir,
    generate_pages,
    make_pdf,
    logger,
    config,
    ComicRequest,
    StoryIdeasRequest,
    StoryIdeasResponse,
    story_ideas,
    generate_comic_cover,
    FullScriptResponse,
    FullScriptRequest,
    generate_full_script,
    GenerateCoverRequest,
    _decode_image_b64,
    upload_to_gcs
)
api_prefix = "/api/v1"
log = logger.get_logger(__name__)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post(api_prefix+"/generate/comic/pages")
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


@app.post(api_prefix+"/generate/comic/ideas", response_model=StoryIdeasResponse)
async def story_ideas_endpoint(req: StoryIdeasRequest) -> StoryIdeasResponse:
    return await story_ideas(req)

@app.post(api_prefix+"/generate/comic/cover")
async def generate_comic_cover_endpoint(
    req: GenerateCoverRequest,
    background_tasks: BackgroundTasks,
):
    log.info("yoyo")
    # Make job dir; auto-clean unless KEEP_OUTPUTS=true
    workdir = make_job_dir()
    if not config.keep_outputs:
        background_tasks.add_task(shutil.rmtree, str(workdir), ignore_errors=True)

    # Optional image save
    ref_path = None
    if req.image_base64:
        try:
            data, ctype = _decode_image_b64(req.image_base64)
        except Exception as e:
            raise HTTPException(400, f"Invalid image_base64: {e}")
        if ctype not in {"image/png", "image/jpeg"}:
            raise HTTPException(400, "image must be PNG or JPEG")
        ref_path = os.path.join(workdir, "cover_ref.png")
        # Always normalize to PNG for downstream tools
        with open(ref_path, "wb") as f:
            f.write(data)

    # Generate cover
    out_path = os.path.join(workdir, "cover.png")
    try:
        generate_comic_cover(
            cover_art_description=req.cover_art_description,
            user_theme=req.user_theme,
            output_path=out_path,
            image_ref_path=ref_path,
        )
    except Exception as e:
        # log.exception("Cover generation failed")  # if you have logging set up
        raise HTTPException(500, f"Cover generation failed: {e}")
    log.debug("koko3")
    mode = req.return_mode
    if mode == "inline":
        return FileResponse(out_path, media_type="image/png", filename="comic_cover.png")
    elif mode == "base64":
        log.debug("koko3")
        with open(out_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return {"mime": "image/png", "base64": b64}
    elif mode == "signed_url":
        info = upload_to_gcs(out_path)  # requires GCS_BUCKET and service account perms
        return {
            "cover": info,
            "meta": {
                "user_theme": req.user_theme,
                "cover_art_description": req.cover_art_description,
            },
        }
    else:
        raise HTTPException(422, "return_mode must be one of: signed_url, inline, base64")

@app.post(api_prefix+"/generate/comic/script", response_model=FullScriptResponse)
async def generate_full_script_endpoint(req: FullScriptRequest) -> FullScriptResponse:
    try:
        return await generate_full_script(req)
    except ValidationError as ve:
        raise HTTPException(status_code=422, detail=f"Schema validation failed: {ve.errors()}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Full script generation failed: {e}")
