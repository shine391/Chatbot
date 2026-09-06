"""Media service for validating, categorizing, and hosting product media URLs."""

import re


class MediaService:
    """Handles image and video URL validation and formatting for rich cards and carousels."""

    def __init__(self) -> None:
        self.image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        self.video_extensions = {".mp4", ".mov", ".webm", ".avi"}

    def is_valid_url(self, url: str) -> bool:
        """Check if string is a valid HTTP/HTTPS URL."""
        return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", url, re.IGNORECASE))

    def filter_valid_images(self, urls: list[str]) -> list[str]:
        """Filter list of URLs to only include valid image URLs."""
        valid_images: list[str] = []
        for url in urls:
            if not self.is_valid_url(url):
                continue
            lower = url.lower()
            if (
                any(lower.endswith(ext) for ext in self.image_extensions)
                or "image" in lower
                or "photo" in lower
                or "pic" in lower
            ):
                valid_images.append(url)
        return valid_images

    def filter_valid_videos(self, urls: list[str]) -> list[str]:
        """Filter list of URLs to only include valid video URLs."""
        valid_videos: list[str] = []
        for url in urls:
            if not self.is_valid_url(url):
                continue
            lower = url.lower()
            if any(lower.endswith(ext) for ext in self.video_extensions) or "video" in lower:
                valid_videos.append(url)
        return valid_videos
