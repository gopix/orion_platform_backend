from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

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
	verapdf_command: str = Field(r"C:\Software\VeraPDF\verapdf.bat", alias="VERAPDF_COMMAND")
	log_dir: str = Field(..., alias="LOG_DIR")
	log_level: str = Field(..., alias="LOG_LEVEL")

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



