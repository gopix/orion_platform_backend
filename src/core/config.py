from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import sys as _sys

# Cross-platform default: Windows bat on Windows, Linux binary otherwise
_DEFAULT_VERAPDF = (
    r"C:\Software\VeraPDF\verapdf.bat"
    if _sys.platform == "win32"
    else "/usr/local/bin/verapdf"
)

class Settings(BaseSettings):
	DB_HOST: str
	DB_PORT: int
	DB_USER: str
	DB_PASSWORD: str
	DB_NAME: str
	upload_dir: str=Field(..., alias="UPLOAD_DIR")
	max_upload_size: int= Field(..., alias="MAX_UPLOAD_SIZE")
	allowed_mime_types: str= Field(..., alias="ALLOWED_MIME_TYPES")
	storage_provider: str
	verapdf_command: str = Field(_DEFAULT_VERAPDF, alias="VERAPDF_COMMAND")
	log_dir: str = Field(..., alias="LOG_DIR")
	log_level: str = Field(..., alias="LOG_LEVEL")

	# Web accessibility scanning (src/modules/accessibility_web) - SSRF guard.
	# Comma-separated list of hosts/IPs (exact match) or CIDR blocks that are
	# permitted to be scanned even though they're private/reserved addresses
	# (see acquisition/url_guard.py). Empty by default - every private/
	# reserved range is rejected unless explicitly opted in here.
	scan_private_ip_allowlist: str = Field("", alias="SCAN_PRIVATE_IP_ALLOWLIST")

	# Book Forge storage
	book_forge_storage_root: str = Field(..., alias="BOOK_FORGE_STORAGE_ROOT")
	book_forge_uploads: str = Field("01_uploads", alias="BOOK_FORGE_UPLOADS")
	book_forge_processing: str = Field("02_processing", alias="BOOK_FORGE_PROCESSING")
	book_forge_temp: str = Field("03_temp", alias="BOOK_FORGE_TEMP")
	book_forge_exports: str = Field("04_exports", alias="BOOK_FORGE_EXPORTS")

	# LLM
	llm_provider: str = Field("anthropic", alias="LLM_PROVIDER")
	anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
	openai_api_key: str = Field("", alias="OPENAI_API_KEY")
	gemini_api_key: str = Field("", alias="GEMINI_API_KEY")
	ollama_host: str = Field("http://localhost:11434", alias="OLLAMA_HOST")

	# Chunking (how parsed documents are split before embedding).
	# Strategy: heading | paragraph | fixed | semantic. "heading" splits on
	# document headings and, with max_chunk_size set, carves oversized sections
	# on paragraph boundaries — so it degrades gracefully on structureless PDFs.
	chunk_strategy: str = Field("heading", alias="CHUNK_STRATEGY")
	chunk_size: int = Field(512, alias="CHUNK_SIZE")            # target tokens (fixed/semantic)
	chunk_overlap: int = Field(50, alias="CHUNK_OVERLAP")       # overlap tokens (fixed)
	chunk_min_size: int = Field(150, alias="CHUNK_MIN_SIZE")    # merge chunks smaller than this
	chunk_max_size: int = Field(600, alias="CHUNK_MAX_SIZE")    # split sections larger than this
	chunk_merge_small: bool = Field(True, alias="CHUNK_MERGE_SMALL")

	# Embeddings
	embedding_provider: str = Field("openai", alias="EMBEDDING_PROVIDER")
	embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")

	# Blueprint retrieval: how many chunks to gather for the blueprint stage.
	# Generous by design — the blueprint needs a broad view of the whole syllabus.
	blueprint_top_k: int = Field(20, alias="BLUEPRINT_TOP_K")
	# Average questions to plan per chapter; the generation prompt scales this by
	# each chapter's exam weightage. Dial total assessment volume without editing
	# the prompt.
	blueprint_questions_per_chapter: int = Field(
	    40, alias="BLUEPRINT_QUESTIONS_PER_CHAPTER"
	)

	# Vector store
	vector_provider: str = Field("pinecone", alias="VECTOR_PROVIDER")
	pinecone_api_key: str = Field("", alias="PINECONE_API_KEY")
	pinecone_index: str = Field("bookforge", alias="PINECONE_INDEX")
	pinecone_cloud: str = Field("aws", alias="PINECONE_CLOUD")
	pinecone_region: str = Field("us-east-1", alias="PINECONE_REGION")

	@property
	def DATABASE_URL(self) -> str:
		return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

	model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

	model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_prefix="",
        extra="ignore",
    )

settings = Settings()



