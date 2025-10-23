"""Configuration models for earnings calendar scraper."""

from typing import Optional
from pydantic import BaseModel, Field


class EarningsScraperConfig(BaseModel):
    """Configuration for earnings calendar scraper."""

    days_ahead: int = Field(
        default=30,
        description="Number of days ahead to fetch earnings data",
        ge=1,
        le=365,
    )
    use_playwright_fallback: bool = Field(
        default=True,
        description="Use Playwright as fallback if API fails",
    )
    timeout: int = Field(
        default=30,
        description="Request timeout in seconds",
        ge=5,
        le=120,
    )


class EarningsDltConfig(BaseModel):
    """Configuration for dlt pipeline."""

    destination: str = Field(
        default="filesystem",
        description="DLT destination type (filesystem, duckdb, etc.)",
    )
    dataset_name: str = Field(
        default="nasdaq_earnings",
        description="Dataset name for the pipeline",
    )
    bucket_url: Optional[str] = Field(
        default=None,
        description="Bucket URL for filesystem destination (e.g., file://./data)",
    )
    write_disposition: str = Field(
        default="replace",
        description="Write disposition (replace for daily snapshots)",
    )


class EarningsCalendarConfig(BaseModel):
    """Combined configuration for earnings calendar pipeline."""

    scraper: EarningsScraperConfig = Field(
        default_factory=EarningsScraperConfig,
        description="Scraper configuration",
    )
    dlt: EarningsDltConfig = Field(
        default_factory=EarningsDltConfig,
        description="DLT pipeline configuration",
    )

    @classmethod
    def from_env(cls) -> "EarningsCalendarConfig":
        """
        Load configuration from environment variables.

        Environment variables:
            EARNINGS_DAYS_AHEAD: Number of days ahead to fetch
            EARNINGS_PLAYWRIGHT_FALLBACK: Use Playwright fallback (true/false)
            EARNINGS_TIMEOUT: Request timeout in seconds
            EARNINGS_DESTINATION: DLT destination type
            EARNINGS_DATASET_NAME: Dataset name
            EARNINGS_BUCKET_URL: Bucket URL for filesystem destination

        Returns:
            Loaded configuration
        """
        import os

        scraper_config = EarningsScraperConfig(
            days_ahead=int(os.getenv("EARNINGS_DAYS_AHEAD", "30")),
            use_playwright_fallback=os.getenv("EARNINGS_PLAYWRIGHT_FALLBACK", "true").lower()
            == "true",
            timeout=int(os.getenv("EARNINGS_TIMEOUT", "30")),
        )

        dlt_config = EarningsDltConfig(
            destination=os.getenv("EARNINGS_DESTINATION", "filesystem"),
            dataset_name=os.getenv("EARNINGS_DATASET_NAME", "nasdaq_earnings"),
            bucket_url=os.getenv("EARNINGS_BUCKET_URL"),
        )

        return cls(scraper=scraper_config, dlt=dlt_config)

    @classmethod
    def from_yaml(cls, path: str) -> "EarningsCalendarConfig":
        """
        Load configuration from YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            Loaded configuration
        """
        import yaml

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return cls(**data)


def get_default_config() -> EarningsCalendarConfig:
    """
    Get default configuration.

    Tries to load from environment variables, falls back to defaults.

    Returns:
        Configuration instance
    """
    try:
        return EarningsCalendarConfig.from_env()
    except Exception:
        return EarningsCalendarConfig()
