import os
import base64
import logging
import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Extract text/prompt from an image using Claude Vision API.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, skipping OCR")
        return ""

    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Detect image type from magic bytes
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = "image/png"
        elif image_bytes[:2] == b'\xff\xd8':
            media_type = "image/jpeg"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            media_type = "image/webp"
        else:
            media_type = "image/jpeg"  # fallback

        logger.info(f"Processing image: {len(image_bytes)} bytes, type: {media_type}")

        payload = {
            "model": "claude-opus-4-5",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64
                            }
                        },
                        {
                            "type": "text",
                            "text": (
                                "This image contains text — likely an AI image generation prompt or instructions. "
                                "Your task: extract ALL text visible in this image EXACTLY as written, "
                                "preserving punctuation, line breaks, and formatting. "
                                "Return ONLY the extracted text with no explanations, no commentary, no preamble. "
                                "If the image has multiple text blocks, include all of them separated by newlines."
                            )
                        }
                    ]
                }
            ]
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        extracted = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                extracted += block.get("text", "")

        result = extracted.strip()
        logger.info(f"Extracted {len(result)} chars of text")
        return result

    except httpx.TimeoutException:
        logger.error("Vision API timeout")
        return ""
    except Exception as e:
        logger.error(f"Vision API error: {type(e).__name__}: {e}")
        return ""
