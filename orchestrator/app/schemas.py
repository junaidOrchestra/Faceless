"""Public API schemas for the orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoStatus = Literal[
    "queued",  # awaiting transcription
    "transcribing",
    "transcribed",  # awaiting LLM
    "llm",
    "awaiting_clip",  # clip search in flight (poller watching)
    "ready",  # prepared; call POST /render to produce the MP4
    "render_queued",
    "rendering",
    "done",
    "failed",
]


class VideoCredentials(BaseModel):
    """Passed through to the CLIP server in memory only."""

    pexels: str | None = None
    pixabay: str | None = None
    flickr: str | None = None


class CreateVideoResponse(BaseModel):
    video_job_id: str = Field(..., examples=["vid-abc"])


class UploadUrlRequest(BaseModel):
    """Request a direct multipart upload session (browser -> bucket)."""

    filename: str | None = Field(default=None, description="Original file name (for the title + extension).")
    content_type: str | None = Field(default=None, description="Browser-declared MIME type.")
    size_bytes: int = Field(..., gt=0, description="Total file size in bytes (used to plan parts).")
    with_audio: bool = Field(
        default=False,
        description=(
            "Also return a presigned PUT URL for a client-extracted narration WAV "
            "so transcription can start before the full video finishes uploading."
        ),
    )


class UploadPartUrl(BaseModel):
    part_number: int = Field(..., description="1-based S3 multipart part number.")
    url: str = Field(..., description="Presigned PUT URL for this part.")


class UploadUrlResponse(BaseModel):
    """A planned multipart upload: PUT each part to its URL, then call finalize."""

    video_job_id: str
    object_key: str = Field(..., description="Bucket key the parts upload into.")
    upload_id: str = Field(..., description="S3 multipart upload id.")
    part_size_bytes: int = Field(..., description="Byte size of every part except the last.")
    parts: list[UploadPartUrl]
    audio_object: str | None = Field(
        default=None, description="Bucket key for the narration WAV (when with_audio)."
    )
    audio_put_url: str | None = Field(
        default=None, description="Presigned single-PUT URL for the narration WAV."
    )


class StartUploadRequest(BaseModel):
    """Start transcription from a client-extracted WAV while the video uploads.

    The narration WAV has already been PUT to ``audio_object``; the full video is
    still uploading to ``object_key`` (completed later via POST /videos/finalize).
    """

    video_job_id: str
    object_key: str = Field(..., description="Bucket key the video is uploading to.")
    audio_object: str = Field(..., description="Bucket key of the already-uploaded narration WAV.")
    filename: str | None = None
    content_type: str | None = None
    video_format: str | None = Field(default=None, alias="format")
    quality: str | None = None
    subtitles: bool = False
    sources: list[str] | None = None
    pexels_key: str | None = None
    pixabay_key: str | None = None
    flickr_key: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class UploadedPartIn(BaseModel):
    part_number: int
    etag: str = Field(..., description="ETag returned by the part PUT response.")


class FinalizeUploadRequest(BaseModel):
    """Complete a multipart upload and enqueue the job for the stored object."""

    video_job_id: str
    object_key: str
    upload_id: str
    parts: list[UploadedPartIn] = Field(..., min_length=1)
    filename: str | None = None
    content_type: str | None = None
    video_format: str | None = Field(
        default=None,
        alias="format",
        description="Output format/aspect (same values as POST /videos 'format').",
    )
    quality: str | None = None
    subtitles: bool = False
    sources: list[str] | None = None
    pexels_key: str | None = None
    pixabay_key: str | None = None
    flickr_key: str | None = None
    # Accepted for forward-compat with the edit-while-uploading flow; unused here.
    transcribe_audio_object: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class ThemeChoice(BaseModel):
    """Content theme: match the script, or fill every beat from a chosen vibe.

    ``mode='script'`` (default) keeps the transcript-driven visual search.
    ``mode='vibe'`` ignores the transcript for visuals and instead searches for
    keywords belonging to ``vibe`` (e.g. 'space', 'forest'); ``vibe`` must be one
    of the known slugs in :mod:`app.vibes`.
    """

    mode: Literal["script", "vibe"] = "script"
    vibe: str | None = Field(
        default=None,
        examples=["space", "forest", "ocean"],
        description="Vibe slug (required when mode='vibe'). See app/vibes.py.",
    )


class PrepareRequest(BaseModel):
    """Output choices supplied after transcription to start the clip search.

    When a job is submitted without a ``format`` it pauses at ``transcribed``
    (beats are ready to review). This request supplies the output shape — which
    drives the orientation/quality of the stock media fetched — and unblocks the
    LLM + clip-search stage. ``subtitles`` is recorded for the later render.
    """

    format: str | None = Field(
        default=None,
        examples=["9:16", "16:9", "1:1", "youtube_shorts"],
        description="Output format/aspect (same values as POST /videos 'format').",
    )
    quality: str | None = Field(
        default=None, description="Downloaded media tier: 'sd' | 'hd' | 'max'."
    )
    subtitles: bool = Field(
        default=False, description="Burn per-beat narration captions at render time."
    )
    theme: ThemeChoice | None = Field(
        default=None,
        description=(
            "Content theme. Omit (or mode='script') to match the transcript; "
            "mode='vibe' fills every beat from the chosen vibe instead."
        ),
    )


class RenderRequest(BaseModel):
    """Optional final-output choices applied just before rendering.

    ``overrides`` maps a beat index to the index of the candidate (within that
    beat's stored ``candidates`` list) the user picked in the editor. Only beats
    whose choice differs from the stored default need to be sent.

    ``format`` / ``subtitles`` let the editor change the output shape and caption
    toggle at render time (e.g. the user switched 9:16 -> 16:9 on the Pick Clips
    screen after the clip search already ran). When omitted, the values stored at
    /prepare are kept. NOTE: the orientation of the *stock media* was chosen at
    clip-search time from the prepared format; changing ``format`` here only
    changes the encoded output dimensions (the renderer cover-scales/crops), not
    which clips were fetched.

    Applying these is idempotent — re-rendering with the same values yields the
    same result — so retries from a flaky client are safe. Out-of-range or
    unknown beats are ignored rather than failing the render.
    """

    overrides: dict[int, int] = Field(
        default_factory=dict,
        examples=[{"3": 1, "7": 2}],
        description="beat_index -> candidate_index (position in the beat's candidates).",
    )
    format: str | None = Field(
        default=None,
        examples=["9:16", "16:9", "1:1", "youtube_shorts"],
        description="Override the output format/aspect (same values as POST /videos 'format').",
    )
    subtitles: bool | None = Field(
        default=None,
        description="Override whether per-beat narration captions are burned in.",
    )
    excluded_beats: list[int] | None = Field(
        default=None,
        examples=[[2, 5]],
        description=(
            "Beat indices to drop from the render. Excluded beats are removed "
            "from both the visual timeline and the narration audio; remaining "
            "beats stitch together contiguously into a shorter video. Omit to "
            "keep any exclusions stored from a prior render request."
        ),
    )
    remove_silence: bool | None = Field(
        default=None,
        description=(
            "Tighten audio: cut detected silences/pauses (and inter-beat dead "
            "air) from the narration so the video plays without gaps. Omit to "
            "keep the value stored from a prior render request."
        ),
    )
    remove_fillers: bool | None = Field(
        default=None,
        description=(
            "Tighten audio: cut filler/hesitation words ('um', 'uh', 'hmm', …) "
            "flagged during transcription. Omit to keep the stored value."
        ),
    )


class VideoStatusResponse(BaseModel):
    video_job_id: str
    status: VideoStatus
    progress: str | None = None
    result_url: str | None = None
    error: str | None = None
    # The content theme chosen for this job (match the script, or a vibe). Read
    # from the job payload so the editor's pick-clips/render screens can show
    # which theme is in effect. Defaults to script when unset.
    theme: ThemeChoice | None = None
    # True when the job was created from a user video upload (footage is available
    # as the default visual on every beat).
    is_video_input: bool = False
    # When true, automatic stock b-roll search was skipped; the editor can opt
    # in via POST /videos/{id}/clips/search-all.
    skip_clip_search: bool | None = None
    # True while the full video is still uploading in the background (edit-while-
    # uploading). Rendering is gated until POST /videos/finalize clears it.
    upload_pending: bool | None = None


class BeatAssignmentOut(BaseModel):
    """The clip selected for a beat. ``platform='generated'`` means a text fallback."""

    platform: str | None = None
    media_url: str | None = None
    preview_url: str | None = None
    kind: str | None = None
    score: float | None = None
    attribution: str | None = None


class BeatCandidateOut(BaseModel):
    """One ranked option for a beat (the default plus alternates the user can pick).

    Tolerates extra keys (``extra="ignore"``): candidates stored for special
    visuals (e.g. an animated text card) carry extra metadata in their JSONB that
    isn't part of this wire shape.
    """

    model_config = ConfigDict(extra="ignore")

    platform: str | None = None
    kind: str | None = None
    media_url: str | None = None
    preview_url: str | None = None
    score: float | None = None
    attribution: str | None = None
    selected: bool = False


class BeatClipResponse(BaseModel):
    """Result of uploading a per-beat recorded clip (e.g. an animated text card)."""

    video_job_id: str
    beat_index: int
    candidate_index: int
    media_url: str | None = None


class BeatInsertResponse(BaseModel):
    """Result of inserting a standalone animated text-card beat.

    Existing beats at/after ``beat_index`` were shifted up by one, so the client
    should re-fetch the beats list. ``duration_s`` is the card's on-screen length.
    """

    video_job_id: str
    beat_index: int
    duration_s: float
    media_url: str | None = None


class WordOut(BaseModel):
    """One transcribed word with timing and a filler flag (compact wire shape)."""

    t: str  # text
    s: float  # start_s
    e: float  # end_s
    f: bool = False  # is_filler


class BeatOut(BaseModel):
    """One beat: transcript text, on-screen timing, queries, and clip choices."""

    index: int
    text: str
    start_s: float
    end_s: float
    queries: dict | None = None
    assignment: BeatAssignmentOut | None = None
    # Up to 3 options (selected first, then alternates), each with preview + media URL.
    candidates: list[BeatCandidateOut] = Field(default_factory=list)
    # Per-word timing + filler flags (empty for jobs transcribed before this
    # existed). Powers filler-word strike-through and the "tighten audio" preview.
    words: list[WordOut] = Field(default_factory=list)
    # Beat origin: "narration" (transcript window) or "insert" (a user-added
    # standalone animated text card with no narration). Inserts last ``duration_s``
    # seconds and contribute a silent gap to the audio track.
    kind: str = "narration"
    duration_s: float | None = None


class BeatsResponse(BaseModel):
    video_job_id: str
    beats: list[BeatOut] = Field(default_factory=list)
    # Detected silence/pause spans across the whole narration ([start_s, end_s]),
    # so the editor can preview how much "remove silences" would shave off.
    silence_spans: list[list[float]] = Field(default_factory=list)


class BeatTextUpdate(BaseModel):
    """Correct the transcript text of one beat — a transcription typo fix.

    The word was spoken correctly, just transcribed wrong, so ONLY the displayed/
    burned caption text changes. Timing, audio, clips, exclusions, and billing are
    untouched. When the corrected text has the same number of whitespace-separated
    tokens as the beat's stored per-word timing, those words are re-synced in place
    (timings + filler flags preserved) so the word-level caption stays consistent.
    """

    text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Corrected beat text.",
        examples=["They sailed past the cape at dawn."],
    )


class BeatTextResponse(BaseModel):
    """Result of correcting a beat's transcript text."""

    video_job_id: str
    beat_index: int
    text: str
    words: list[WordOut] = Field(default_factory=list)


class BeatSplitRequest(BaseModel):
    """Where to split a beat: the index of the first word of the SECOND half.

    ``word_index`` is 1-based-exclusive over the beat's per-word list, i.e. it must
    be ``1 <= word_index < len(words)`` so both halves keep at least one word.
    """

    word_index: int = Field(
        ...,
        ge=1,
        description="First word index of the second half (1..len(words)-1).",
        examples=[3],
    )


class BeatSplitResponse(BaseModel):
    """Result of splitting a beat at a word boundary into two beats.

    The original beat keeps the words before the cut (``first_index``); a new beat
    holds the rest (``second_index``). Every later beat shifted up by one, so the
    client should re-fetch the beats list.
    """

    video_job_id: str
    first_index: int
    second_index: int
    beat_count: int


class BeatMergeResponse(BaseModel):
    """Result of merging a beat with the one after it.

    The two beats become one (``beat_index``) spanning both narration windows;
    every later beat shifted down by one, so the client should re-fetch the beats
    list.
    """

    video_job_id: str
    beat_index: int
    beat_count: int


class TierInfo(BaseModel):
    """Per-tier limits surfaced to the client (mirrors app.tiers.TierConfig)."""

    name: str
    label: str
    monthly_credits: int
    max_video_seconds: int
    max_resolution_height: int
    watermark: bool
    unlimited_credits: bool = False
    features: list[str] = Field(default_factory=list)


FeedbackCategory = Literal["suggestion", "improvement", "bug", "praise", "other"]


class FeedbackRequest(BaseModel):
    """A user-submitted note. Only ``category`` + ``message`` are required."""

    category: FeedbackCategory = "suggestion"
    message: str = Field(
        ...,
        min_length=3,
        max_length=4000,
        description="The user's suggestion / improvement / bug report.",
        examples=["A timeline scrubber on the pick-clips screen would be amazing."],
    )
    rating: int | None = Field(
        default=None, ge=1, le=5, description="Optional 1-5 satisfaction signal."
    )
    email: str | None = Field(
        default=None,
        max_length=320,
        description="Optional reply-to (defaults to the account email).",
    )
    page: str | None = Field(
        default=None, max_length=512, description="Page/path the user was on."
    )


class FeedbackResponse(BaseModel):
    """Acknowledgement returned after a feedback row is stored."""

    id: int
    status: Literal["received"] = "received"


class MeResponse(BaseModel):
    """The authenticated user's account summary."""

    id: str
    email: str | None = None
    name: str | None = None
    tier: str
    credits: int
    tier_info: TierInfo


class CreditTransactionOut(BaseModel):
    id: int
    delta: int
    reason: str
    project_id: str | None = None
    created_at: str


class CreditsResponse(BaseModel):
    credits: int
    transactions: list[CreditTransactionOut] = Field(default_factory=list)


class ProjectOut(BaseModel):
    id: str
    title: str | None = None
    input_type: str | None = None
    status: str
    # Fine-grained pipeline stage of the underlying job (e.g. "transcribing",
    # "llm_vocabulary", "rendering") so the UI can show *where* a processing
    # project is, and the failure reason when it failed. Both are None when the
    # job row is absent.
    progress: str | None = None
    error: str | None = None
    result_url: str | None = None
    created_at: str
    updated_at: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectOut] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    detail: str
